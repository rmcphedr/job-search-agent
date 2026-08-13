"""Persistent application-preparation checklist state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.database.db import get_connection
from src.database.migrate import apply_migrations

STEP_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("requirements", "Inspect application requirements"),
    ("resume", "Tailor resume for this role"),
    ("personal_details", "Fill personal details"),
    ("technical_questions", "Prepare technical answers"),
    ("cover_letter", "Write cover letter, if required"),
    ("final_review", "Review the complete application"),
)
VALID_STEP_STATUSES = frozenset({"pending", "in_progress", "complete", "not_required"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_application_preparation(job_id: int) -> list[dict[str, Any]]:
    """Create missing steps and atomically move a tracked job to applying."""
    connection = get_connection()
    try:
        apply_migrations(connection)
        tracked = connection.execute(
            "SELECT 1 FROM tracked_jobs WHERE job_id = ?;", (job_id,)
        ).fetchone()
        if tracked is None:
            raise ValueError(f"Job {job_id} is not tracked")

        now = _utc_now()
        for position, (step_key, title) in enumerate(STEP_DEFINITIONS, start=1):
            connection.execute(
                """
                INSERT OR IGNORE INTO application_preparation_steps
                    (job_id, step_key, title, position, status, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?);
                """,
                (job_id, step_key, title, position, now),
            )
        connection.execute(
            "UPDATE tracked_jobs SET stage = 'applying', updated_at = ? WHERE job_id = ?;",
            (now, job_id),
        )
        connection.commit()
        return _list_steps(connection, job_id)
    finally:
        connection.close()


def list_application_steps(job_id: int) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        return _list_steps(connection, job_id)
    finally:
        connection.close()


def update_application_step(
    job_id: int,
    step_key: str,
    *,
    status: str,
    details: str = "",
) -> dict[str, Any] | None:
    normalized = status.strip().lower()
    if normalized not in VALID_STEP_STATUSES:
        raise ValueError(f"Invalid application step status: {status}")

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE application_preparation_steps
            SET status = ?, details = ?, updated_at = ?
            WHERE job_id = ? AND step_key = ?;
            """,
            (normalized, details.strip(), _utc_now(), job_id, step_key),
        )
        connection.commit()
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            "SELECT * FROM application_preparation_steps WHERE job_id = ? AND step_key = ?;",
            (job_id, step_key),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def preparation_is_complete(steps: list[dict[str, Any]]) -> bool:
    return bool(steps) and all(
        str(step.get("status")) in {"complete", "not_required"} for step in steps
    )


def _list_steps(connection, job_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM application_preparation_steps
        WHERE job_id = ? ORDER BY position;
        """,
        (job_id,),
    ).fetchall()
    return [dict(row) for row in rows]
