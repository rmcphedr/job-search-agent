"""Persistence for quick-review inbox decisions."""

from __future__ import annotations

from datetime import datetime, timezone

from src.database.db import get_connection
from src.database.migrate import apply_migrations

VALID_DECISIONS = frozenset({"maybe", "declined", "accepted"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_review_decision(job_id: int, decision: str) -> None:
    """Create or replace the review decision for a job."""
    normalized = decision.strip().lower()
    if normalized not in VALID_DECISIONS:
        raise ValueError(f"Invalid review decision: {decision}")

    now = _utc_now()
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO job_reviews (job_id, decision, reviewed_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                decision = excluded.decision,
                updated_at = excluded.updated_at;
            """,
            (job_id, normalized, now, now),
        )
        connection.commit()
    finally:
        connection.close()


def get_review_decisions() -> dict[int, str]:
    """Return job_id to decision for every reviewed job."""
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        rows = connection.execute("SELECT job_id, decision FROM job_reviews;").fetchall()
        return {int(row["job_id"]): str(row["decision"]) for row in rows}
    finally:
        connection.close()
