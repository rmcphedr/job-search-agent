"""Persist filtered job candidates to SQLite without duplicates."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.database.db import get_connection
from src.jobs.job_models import JobCandidate
from src.jobs.job_url_utils import compute_content_hash, normalize_job_url


@dataclass
class SaveJobsResult:
    inserted: int = 0
    duplicates_skipped: int = 0
    updated: int = 0


def resolve_company_id(connection: sqlite3.Connection, candidate: JobCandidate) -> int | None:
    if candidate.company_id is not None:
        row = connection.execute(
            "SELECT company_id FROM companies WHERE company_id = ? LIMIT 1;",
            (candidate.company_id,),
        ).fetchone()
        if row is not None:
            return int(row["company_id"])

    row = connection.execute(
        "SELECT company_id FROM companies WHERE company_name = ? COLLATE NOCASE LIMIT 1;",
        (candidate.company_name,),
    ).fetchone()
    if row is not None:
        return int(row["company_id"])

    return None


def _find_existing_job_id(
    connection: sqlite3.Connection,
    *,
    company_id: int,
    title: str,
    location: str | None,
    url: str | None,
    content_hash: str,
) -> int | None:
    normalized_url = normalize_job_url(url)
    if normalized_url:
        row = connection.execute(
            "SELECT job_id FROM job_postings WHERE url = ? LIMIT 1;",
            (normalized_url,),
        ).fetchone()
        if row is not None:
            return int(row["job_id"])

    row = connection.execute(
        """
        SELECT job_id FROM job_postings
        WHERE company_id = ?
          AND lower(title) = lower(?)
          AND coalesce(lower(location), '') = coalesce(lower(?), '')
        LIMIT 1;
        """,
        (company_id, title, location or ""),
    ).fetchone()
    if row is not None:
        return int(row["job_id"])

    rows = connection.execute(
        "SELECT job_id, title, description, url FROM job_postings WHERE company_id = ?;",
        (company_id,),
    ).fetchall()
    for existing in rows:
        existing_hash = compute_content_hash(
            existing["title"],
            existing["description"],
            existing["url"],
        )
        if existing_hash == content_hash:
            return int(existing["job_id"])
    return None


def _build_fit_reason(candidate: JobCandidate) -> str:
    keywords = ", ".join(candidate.matched_keywords[:8])
    provider = candidate.provider or "unknown"
    parts = [f"provider={provider}"]
    if candidate.triage_score is not None:
        parts.append(f"triage={candidate.triage_score:.1f}")
    if keywords:
        parts.append(f"matched={keywords}")
    else:
        parts.append("matched=none")
    if candidate.llm_fit_score is not None:
        parts.append(f"llm_fit={candidate.llm_fit_score:.1f}")
    return "; ".join(parts)


def _resolve_fit_score(candidate: JobCandidate) -> float:
    if candidate.llm_fit_score is not None:
        return round(candidate.llm_fit_score, 2)
    return round(candidate.keyword_score * 10, 2)


def save_jobs(
    candidates: list[JobCandidate],
    *,
    force_refresh: bool = False,
) -> SaveJobsResult:
    """Insert new jobs into job_postings, skipping duplicates unless force_refresh."""
    result = SaveJobsResult()
    connection = get_connection()

    try:
        for candidate in candidates:
            company_id = resolve_company_id(connection, candidate)
            if company_id is None:
                continue

            content_hash = candidate.content_hash or compute_content_hash(
                candidate.title,
                candidate.description,
                candidate.url,
            )
            existing_job_id = _find_existing_job_id(
                connection,
                company_id=company_id,
                title=candidate.title,
                location=candidate.location,
                url=candidate.url,
                content_hash=content_hash,
            )

            fit_score = _resolve_fit_score(candidate)
            fit_reason = _build_fit_reason(candidate)

            if existing_job_id is not None:
                if force_refresh:
                    connection.execute(
                        """
                        UPDATE job_postings
                        SET title = ?,
                            location = ?,
                            url = ?,
                            description = ?,
                            active = 1,
                            fit_score = ?,
                            fit_reason = ?
                        WHERE job_id = ?;
                        """,
                        (
                            candidate.title,
                            candidate.location,
                            candidate.url,
                            candidate.description,
                            fit_score,
                            fit_reason,
                            existing_job_id,
                        ),
                    )
                    result.updated += 1
                else:
                    result.duplicates_skipped += 1
                continue

            connection.execute(
                """
                INSERT INTO job_postings (
                    company_id,
                    title,
                    location,
                    url,
                    description,
                    active,
                    fit_score,
                    fit_reason
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?);
                """,
                (
                    company_id,
                    candidate.title,
                    candidate.location,
                    candidate.url,
                    candidate.description,
                    fit_score,
                    fit_reason,
                ),
            )
            result.inserted += 1

        connection.commit()
    finally:
        connection.close()

    return result

