"""Persistent employer-to-ATS source registry and source discovery."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from src.database.migrate import apply_migrations
from src.jobs.employer_ats_adapters import (
    AshbyAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    WorkdayAdapter,
)
from src.jobs.job_url_utils import detect_provider_from_html, detect_provider_from_url

SUPPORTED_ATS_PROVIDERS = ("greenhouse", "lever", "ashby", "workday")


@dataclass(frozen=True)
class EmployerATSSource:
    ats_source_id: int
    company_id: int
    company_name: str
    provider: str
    board_url: str
    board_token: str | None
    enabled: bool
    discovery_method: str
    status: str
    last_checked_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None


def _first_provider_url(html: str, provider: str) -> str | None:
    patterns = {
        "greenhouse": r"https?://(?:boards|job-boards)\.greenhouse\.io/[^\"'<>\s]+",
        "lever": r"https?://jobs\.lever\.co/[^\"'<>\s]+",
        "ashby": r"https?://jobs\.ashbyhq\.com/[^\"'<>\s]+",
        "workday": r"https?://[^\"'<>\s]+(?:my)?workdayjobs\.com/[^\"'<>\s]+",
    }
    match = re.search(patterns[provider], html, flags=re.I)
    return match.group(0).rstrip("/.,);&") if match else None


def identify_ats_source(url: str, html: str = "") -> tuple[str, str, str | None] | None:
    """Return provider, canonical board URL, and board token for a known ATS page."""
    provider = detect_provider_from_url(url) or detect_provider_from_html(html)
    if provider not in SUPPORTED_ATS_PROVIDERS:
        return None
    provider_url = url if detect_provider_from_url(url) == provider else _first_provider_url(html, provider)
    if not provider_url:
        return None

    if provider == "greenhouse":
        token = GreenhouseAdapter.board_token(provider_url, html)
        return (provider, f"https://job-boards.greenhouse.io/{token}", token) if token else None
    if provider == "lever":
        token = LeverAdapter.site_token(provider_url, html)
        return (provider, f"https://jobs.lever.co/{token}", token) if token else None
    if provider == "ashby":
        token = AshbyAdapter.board_token(provider_url, html)
        return (provider, f"https://jobs.ashbyhq.com/{token}", token) if token else None

    coordinates = WorkdayAdapter.coordinates(provider_url)
    if not coordinates:
        return None
    host, tenant, site = coordinates
    return provider, f"https://{host}/{site}", f"{tenant}/{site}"


def upsert_ats_source(
    connection: sqlite3.Connection,
    *,
    company_id: int,
    provider: str,
    board_url: str,
    board_token: str | None,
    discovery_method: str,
) -> int:
    apply_migrations(connection)
    connection.execute(
        """
        INSERT INTO employer_ats_sources (
            company_id, provider, board_url, board_token, discovery_method
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(company_id, provider, board_url) DO UPDATE SET
            board_token = coalesce(excluded.board_token, employer_ats_sources.board_token),
            discovery_method = excluded.discovery_method,
            enabled = 1,
            updated_at = CURRENT_TIMESTAMP;
        """,
        (company_id, provider, board_url, board_token, discovery_method),
    )
    row = connection.execute(
        """SELECT ats_source_id FROM employer_ats_sources
           WHERE company_id = ? AND provider = ? AND board_url = ?;""",
        (company_id, provider, board_url),
    ).fetchone()
    return int(row["ats_source_id"])


def list_ats_sources(
    connection: sqlite3.Connection,
    *,
    provider: str | None = None,
    company: str | None = None,
    enabled_only: bool = True,
) -> list[EmployerATSSource]:
    apply_migrations(connection)
    clauses: list[str] = []
    params: list[object] = []
    if enabled_only:
        clauses.append("s.enabled = 1")
    if provider:
        clauses.append("s.provider = ?")
        params.append(provider)
    if company:
        clauses.append("lower(c.company_name) LIKE ?")
        params.append(f"%{company.casefold()}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"""
        SELECT s.*, c.company_name
        FROM employer_ats_sources s
        JOIN companies c ON c.company_id = s.company_id
        {where}
        ORDER BY s.provider, c.company_name;
        """,
        params,
    ).fetchall()
    return [
        EmployerATSSource(
            ats_source_id=int(row["ats_source_id"]),
            company_id=int(row["company_id"]),
            company_name=str(row["company_name"]),
            provider=str(row["provider"]),
            board_url=str(row["board_url"]),
            board_token=row["board_token"],
            enabled=bool(row["enabled"]),
            discovery_method=str(row["discovery_method"]),
            status=str(row["status"]),
            last_checked_at=row["last_checked_at"],
            last_success_at=row["last_success_at"],
            last_error=row["last_error"],
        )
        for row in rows
    ]


def update_ats_source_status(
    connection: sqlite3.Connection,
    source_id: int,
    *,
    status: str,
    error: str | None = None,
) -> None:
    success_sql = ", last_success_at = CURRENT_TIMESTAMP" if status == "healthy" else ""
    connection.execute(
        f"""UPDATE employer_ats_sources
            SET status = ?, last_checked_at = CURRENT_TIMESTAMP,
                last_error = ?, updated_at = CURRENT_TIMESTAMP{success_sql}
            WHERE ats_source_id = ?;""",
        (status, error, source_id),
    )


def backfill_legacy_ats_job_sources(connection: sqlite3.Connection) -> int:
    """Label legacy career-page rows whose URLs unambiguously identify an ATS."""
    updates = (
        ("greenhouse", "%greenhouse.io/%"),
        ("lever", "%jobs.lever.co/%"),
        ("ashby", "%jobs.ashbyhq.com/%"),
        ("workday", "%workdayjobs.com/%"),
    )
    changed = 0
    for provider, pattern in updates:
        cursor = connection.execute(
            """UPDATE job_postings SET source_board = ?
               WHERE (source_board IS NULL OR trim(source_board) = '')
                 AND lower(url) LIKE ?;""",
            (provider, pattern),
        )
        changed += max(cursor.rowcount, 0)
    return changed
