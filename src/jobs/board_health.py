"""Board source health summaries for the dashboard."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.database.db import get_connection
from src.jobs.board_discovery.config import BoardSource, load_board_sources_config

HEALTH_LABELS = {
    "healthy": "Healthy",
    "warning": "Warning",
    "error": "Error",
    "disabled": "Disabled",
    "stub": "Not implemented",
    "not_run": "Not run yet",
    "unknown": "Unknown",
}

LEGACY_RUN_PATTERN = re.compile(
    r"run_id=(?P<run_id>\S+)\s+boards=(?P<boards>\d+)\s+raw=(?P<raw>\d+)"
    r"(?:\s+filtered=(?P<filtered>\d+))?(?:\s+inserted=(?P<inserted>\d+))?"
)


@dataclass(frozen=True)
class BoardRunSnapshot:
    source_id: str
    run_at: str
    raw_jobs: int = 0
    filtered_jobs: int = 0
    queries_run: int = 0
    notes: str = ""
    run_id: str = ""


def load_job_counts_by_source() -> dict[str, dict[str, int]]:
    """Return source_board → {total, active} job counts."""
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT
                COALESCE(NULLIF(TRIM(source_board), ''), '__career_page__') AS source_key,
                COUNT(*) AS total_jobs,
                SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active_jobs
            FROM job_postings
            GROUP BY source_key;
            """
        ).fetchall()
    finally:
        connection.close()

    return {
        str(row["source_key"]): {
            "total": int(row["total_jobs"]),
            "active": int(row["active_jobs"]),
        }
        for row in rows
    }


def load_board_discovery_runs(limit: int = 50) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT run_id, run_type, started_at, completed_at, companies_checked, notes
            FROM runs
            WHERE run_type = 'board_discovery'
            ORDER BY run_id DESC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def parse_board_run_notes(notes: str) -> dict[str, Any]:
    """Parse board_discovery run notes (JSON or legacy string)."""
    text = (notes or "").strip()
    if not text:
        return {}

    if text.startswith("{"):
        try:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {"legacy_text": text}

    if text.startswith("dry_run"):
        text = text.replace("dry_run ", "", 1)

    match = LEGACY_RUN_PATTERN.search(text)
    if match:
        return {
            "run_id": match.group("run_id"),
            "boards_checked": int(match.group("boards")),
            "raw_jobs_found": int(match.group("raw")),
            "jobs_after_filter": int(match.group("filtered") or 0),
            "inserted": int(match.group("inserted") or 0),
            "legacy_text": notes,
            "boards": [],
        }

    return {"legacy_text": text}


def latest_board_run_snapshots(runs: list[dict[str, Any]]) -> dict[str, BoardRunSnapshot]:
    """Build latest per-board snapshot from board_discovery run history."""
    snapshots: dict[str, BoardRunSnapshot] = {}

    for run in runs:
        run_at = str(run.get("completed_at") or run.get("started_at") or "")
        payload = parse_board_run_notes(str(run.get("notes") or ""))
        run_id = str(payload.get("run_id") or "")

        for board_row in payload.get("boards", []):
            if not isinstance(board_row, dict):
                continue
            source_id = str(board_row.get("source_id", "")).strip()
            if not source_id:
                continue
            candidate = BoardRunSnapshot(
                source_id=source_id,
                run_at=run_at,
                raw_jobs=int(board_row.get("raw_jobs") or 0),
                filtered_jobs=int(board_row.get("filtered_jobs") or 0),
                queries_run=int(board_row.get("queries_run") or 0),
                notes=str(board_row.get("notes") or ""),
                run_id=run_id,
            )
            existing = snapshots.get(source_id)
            if existing is None or candidate.run_at >= existing.run_at:
                snapshots[source_id] = candidate

    return snapshots


def classify_board_health(
    board: BoardSource,
    *,
    job_total: int,
    last_run: BoardRunSnapshot | None,
) -> tuple[str, str]:
    if not board.enabled:
        return "disabled", HEALTH_LABELS["disabled"]
    if board.adapter == "stub":
        return "stub", HEALTH_LABELS["stub"]

    if last_run is not None:
        notes = last_run.notes.strip().lower()
        if notes.startswith("error:"):
            return "error", HEALTH_LABELS["error"]
        if "blocked" in notes or "captcha" in notes or "403" in notes:
            return "error", HEALTH_LABELS["error"]
        if last_run.raw_jobs > 0 or job_total > 0:
            return "healthy", HEALTH_LABELS["healthy"]
        if last_run.queries_run > 0:
            return "warning", HEALTH_LABELS["warning"]

    if job_total > 0:
        return "healthy", HEALTH_LABELS["healthy"]

    return "not_run", HEALTH_LABELS["not_run"]


def build_board_health_frame() -> pd.DataFrame:
    """Merge board config, SQLite job counts, and latest run snapshots."""
    config = load_board_sources_config()
    job_counts = load_job_counts_by_source()
    runs = load_board_discovery_runs()
    snapshots = latest_board_run_snapshots(runs)

    rows: list[dict[str, object]] = []
    for board in config.boards:
        counts = job_counts.get(board.source_id, {"total": 0, "active": 0})
        last_run = snapshots.get(board.source_id)
        health, health_label = classify_board_health(
            board,
            job_total=int(counts["total"]),
            last_run=last_run,
        )
        rows.append(
            {
                "source_id": board.source_id,
                "name": board.name,
                "enabled": board.enabled,
                "phase": board.phase,
                "priority": board.priority,
                "adapter": board.adapter,
                "scrape_mode": board.scrape_mode,
                "base_url": board.base_url,
                "config_notes": board.notes,
                "jobs_total": int(counts["total"]),
                "jobs_active": int(counts["active"]),
                "last_run_at": last_run.run_at if last_run else "",
                "last_raw_jobs": last_run.raw_jobs if last_run else 0,
                "last_queries_run": last_run.queries_run if last_run else 0,
                "last_run_notes": last_run.notes if last_run else "",
                "health_status": health,
                "health_label": health_label,
            }
        )

    return pd.DataFrame(rows)


def build_other_source_rows() -> pd.DataFrame:
    """Jobs from sources not in the board catalog (career pages, unmapped boards)."""
    config = load_board_sources_config()
    known_ids = {board.source_id for board in config.boards}
    known_ids.update({"greenhouse", "lever", "ashby", "workday"})
    job_counts = load_job_counts_by_source()

    rows: list[dict[str, object]] = []
    career = job_counts.get("__career_page__", {"total": 0, "active": 0})
    if career["total"] > 0:
        rows.append(
            {
                "source_id": "career_page",
                "name": "Company career pages",
                "enabled": True,
                "jobs_total": career["total"],
                "jobs_active": career["active"],
                "health_status": "healthy",
                "health_label": HEALTH_LABELS["healthy"],
                "notes": "Jobs from website/career-page discovery pipeline",
            }
        )

    for source_key, counts in sorted(job_counts.items()):
        if source_key in known_ids or source_key == "__career_page__":
            continue
        display_id = source_key.replace("__career_page__", "career_page")
        rows.append(
            {
                "source_id": display_id,
                "name": display_id.replace("_", " ").title(),
                "enabled": False,
                "jobs_total": counts["total"],
                "jobs_active": counts["active"],
                "health_status": "unknown",
                "health_label": "Not in catalog",
                "notes": "Jobs stored under this source_board but no matching config entry",
            }
        )

    return pd.DataFrame(rows)


def build_employer_ats_source_frame() -> pd.DataFrame:
    """Aggregate registered employer ATS sources and stored jobs by provider."""
    connection = get_connection()
    try:
        from src.database.migrate import apply_migrations

        apply_migrations(connection)
        connection.commit()
        rows = connection.execute(
            """
            SELECT
                s.provider,
                COUNT(*) AS employers,
                SUM(CASE WHEN s.enabled = 1 THEN 1 ELSE 0 END) AS enabled_sources,
                SUM(CASE WHEN s.status = 'healthy' THEN 1 ELSE 0 END) AS healthy_sources,
                SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) AS error_sources,
                MAX(s.last_checked_at) AS last_checked_at,
                MAX(s.last_success_at) AS last_success_at,
                GROUP_CONCAT(DISTINCT c.company_name) AS companies
            FROM employer_ats_sources s
            JOIN companies c ON c.company_id = s.company_id
            GROUP BY s.provider
            ORDER BY s.provider;
            """
        ).fetchall()
        job_rows = connection.execute(
            """SELECT source_board, COUNT(*) total,
                      SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) active
               FROM job_postings
               WHERE source_board IN ('greenhouse', 'lever', 'ashby', 'workday')
               GROUP BY source_board;"""
        ).fetchall()
    finally:
        connection.close()
    job_counts = {
        str(row["source_board"]): (int(row["total"]), int(row["active"]))
        for row in job_rows
    }
    return pd.DataFrame(
        [
            {
                "provider": str(row["provider"]),
                "employers": int(row["employers"]),
                "enabled_sources": int(row["enabled_sources"]),
                "healthy_sources": int(row["healthy_sources"]),
                "error_sources": int(row["error_sources"]),
                "jobs_total": job_counts.get(str(row["provider"]), (0, 0))[0],
                "jobs_active": job_counts.get(str(row["provider"]), (0, 0))[1],
                "last_checked_at": row["last_checked_at"],
                "last_success_at": row["last_success_at"],
                "companies": row["companies"] or "",
            }
            for row in rows
        ]
    )


def build_board_health_summary(frame: pd.DataFrame) -> dict[str, int]:
    enabled = frame[frame["enabled"] == True]  # noqa: E712
    return {
        "total_boards": len(frame),
        "enabled_boards": len(enabled),
        "healthy_boards": int((enabled["health_status"] == "healthy").sum()),
        "warning_boards": int((enabled["health_status"] == "warning").sum()),
        "error_boards": int((enabled["health_status"] == "error").sum()),
        "not_run_boards": int((enabled["health_status"] == "not_run").sum()),
        "total_board_jobs": int(frame["jobs_total"].sum()),
    }
