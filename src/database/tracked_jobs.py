"""CRUD helpers for user-tracked job applications."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.database.db import get_connection

TRACKING_STAGES: tuple[tuple[str, str], ...] = (
    ("tracked", "Tracked"),
    ("applying", "Applying"),
    ("applied", "Applied"),
    ("interviewing", "Interviewing"),
    ("accepted", "Accepted"),
    ("rejected", "Rejected"),
    ("withdrawn", "Withdrawn"),
)

TERMINAL_STAGES = frozenset({"rejected", "withdrawn", "accepted"})
STAGE_LABELS = dict(TRACKING_STAGES)
VALID_STAGES = frozenset(STAGE_LABELS)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_stage(stage: str) -> str:
    normalized = stage.strip().lower()
    if normalized not in VALID_STAGES:
        raise ValueError(f"Invalid tracking stage: {stage}")
    return normalized


def track_jobs(job_ids: list[int], *, stage: str = "tracked") -> int:
    """Add multiple jobs to tracking. Returns count processed."""
    for job_id in job_ids:
        track_job(job_id, stage=stage)
    return len(job_ids)


def untrack_jobs(job_ids: list[int]) -> int:
    """Remove multiple jobs from tracking. Returns count removed."""
    removed = 0
    for job_id in job_ids:
        if untrack_job(job_id):
            removed += 1
    return removed


def get_tracked_stage_map() -> dict[int, str]:
    """Return job_id → stage for all tracked jobs."""
    connection = get_connection()
    try:
        rows = connection.execute("SELECT job_id, stage FROM tracked_jobs;").fetchall()
        return {int(row["job_id"]): str(row["stage"]) for row in rows}
    finally:
        connection.close()


def track_job(
    job_id: int,
    *,
    stage: str = "tracked",
    notes: str | None = None,
) -> dict[str, Any]:
    """Add a job to the tracking inventory or return the existing row."""
    normalized_stage = _normalize_stage(stage)
    now = _utc_now()
    applied_at = now if normalized_stage == "applied" else None

    connection = get_connection()
    try:
        existing = connection.execute(
            "SELECT tracked_id, job_id, stage FROM tracked_jobs WHERE job_id = ?;",
            (job_id,),
        ).fetchone()
        if existing is not None:
            return dict(existing)

        cursor = connection.execute(
            """
            INSERT INTO tracked_jobs (job_id, stage, notes, applied_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (job_id, normalized_stage, notes, applied_at, now, now),
        )
        connection.commit()
        tracked_id = int(cursor.lastrowid)
        row = connection.execute(
            "SELECT * FROM tracked_jobs WHERE tracked_id = ?;",
            (tracked_id,),
        ).fetchone()
        return dict(row) if row is not None else {"tracked_id": tracked_id, "job_id": job_id}
    finally:
        connection.close()


def untrack_job(job_id: int) -> bool:
    """Remove a job from tracking. Returns True when a row was deleted."""
    connection = get_connection()
    try:
        cursor = connection.execute(
            "DELETE FROM tracked_jobs WHERE job_id = ?;",
            (job_id,),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def update_tracked_stage(job_id: int, stage: str) -> dict[str, Any] | None:
    """Update the pipeline stage for a tracked job."""
    normalized_stage = _normalize_stage(stage)
    now = _utc_now()

    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT tracked_id, applied_at FROM tracked_jobs WHERE job_id = ?;",
            (job_id,),
        ).fetchone()
        if row is None:
            return None

        applied_at = row["applied_at"]
        if normalized_stage == "applied" and not applied_at:
            applied_at = now

        connection.execute(
            """
            UPDATE tracked_jobs
            SET stage = ?, applied_at = ?, updated_at = ?
            WHERE job_id = ?;
            """,
            (normalized_stage, applied_at, now, job_id),
        )
        connection.commit()
        updated = connection.execute(
            "SELECT * FROM tracked_jobs WHERE job_id = ?;",
            (job_id,),
        ).fetchone()
        return dict(updated) if updated is not None else None
    finally:
        connection.close()


def update_tracked_notes(job_id: int, notes: str) -> dict[str, Any] | None:
    """Update free-form notes for a tracked job."""
    connection = get_connection()
    try:
        connection.execute(
            """
            UPDATE tracked_jobs
            SET notes = ?, updated_at = ?
            WHERE job_id = ?;
            """,
            (notes, _utc_now(), job_id),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM tracked_jobs WHERE job_id = ?;",
            (job_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def is_job_tracked(job_id: int) -> bool:
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT 1 FROM tracked_jobs WHERE job_id = ? LIMIT 1;",
            (job_id,),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def get_tracked_job(job_id: int) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM tracked_jobs WHERE job_id = ?;",
            (job_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def list_tracked_jobs() -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT
                t.tracked_id,
                t.job_id,
                t.stage,
                t.notes,
                t.applied_at,
                t.created_at,
                t.updated_at,
                j.title,
                j.location,
                j.url,
                j.fit_score,
                j.keyword_score,
                j.active,
                c.company_name,
                c.company_id
            FROM tracked_jobs AS t
            INNER JOIN job_postings AS j ON t.job_id = j.job_id
            INNER JOIN companies AS c ON j.company_id = c.company_id
            ORDER BY
                CASE t.stage
                    WHEN 'tracked' THEN 1
                    WHEN 'applying' THEN 2
                    WHEN 'applied' THEN 3
                    WHEN 'interviewing' THEN 4
                    WHEN 'accepted' THEN 5
                    WHEN 'rejected' THEN 6
                    WHEN 'withdrawn' THEN 7
                    ELSE 8
                END,
                t.updated_at DESC;
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()
