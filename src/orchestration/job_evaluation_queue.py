"""Transactional lifecycle for durable agent job-evaluation work."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.database.db import SCHEMA_FILE, get_connection
from src.database.migrate import apply_migrations


@dataclass(frozen=True)
class QueueItem:
    queue_id: int
    job_id: int
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    requested_model: str
    requested_reasoning_effort: str
    defer_reason: str | None = None
    lease_owner: str | None = None
    lease_expires_at: str | None = None


def _item(row: sqlite3.Row) -> QueueItem:
    return QueueItem(**{field: row[field] for field in QueueItem.__dataclass_fields__})


def _with_connection(connection: sqlite3.Connection | None):
    owned = connection is None
    conn = connection or get_connection()
    conn.row_factory = sqlite3.Row
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_postings'").fetchone() is None:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    apply_migrations(conn)
    return conn, owned


def enqueue_job(
    job_id: int,
    *,
    description_ready: bool,
    priority: int = 100,
    reactivate: bool = False,
    connection: sqlite3.Connection | None = None,
) -> QueueItem:
    conn, owned = _with_connection(connection)
    status = "queued" if description_ready else "deferred"
    reason = None if description_ready else "description_not_verified"
    try:
        existing = conn.execute("SELECT status FROM job_evaluation_queue WHERE job_id=?", (job_id,)).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO job_evaluation_queue
                   (job_id,status,priority,defer_reason,eligible_at)
                   VALUES (?,?,?,?,CASE WHEN ?='queued' THEN CURRENT_TIMESTAMP END)""",
                (job_id, status, priority, reason, status),
            )
        elif existing["status"] != "completed" or reactivate:
            conn.execute(
                """UPDATE job_evaluation_queue SET status=?, priority=?, defer_reason=?,
                   eligible_at=CASE WHEN ?='queued' THEN CURRENT_TIMESTAMP END,
                   attempt_count=CASE WHEN ? THEN 0 ELSE attempt_count END,
                   lease_owner=NULL, lease_expires_at=NULL, claimed_at=NULL,
                   completed_at=NULL, last_error=NULL, updated_at=CURRENT_TIMESTAMP
                   WHERE job_id=?""",
                (status, priority, reason, status, int(reactivate), job_id),
            )
        row = conn.execute("SELECT * FROM job_evaluation_queue WHERE job_id=?", (job_id,)).fetchone()
        if owned:
            conn.commit()
        return _item(row)
    finally:
        if owned:
            conn.close()


def sync_job_eligibility(job_id: int, *, description_ready: bool, reactivate: bool = False, connection=None) -> QueueItem:
    return enqueue_job(job_id, description_ready=description_ready, reactivate=reactivate, connection=connection)


def claim_batch(*, run_id: str, worker_id: str, limit: int, lease_seconds: int, connection=None) -> list[QueueItem]:
    conn, owned = _with_connection(connection)
    try:
        if owned:
            conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """SELECT queue_id FROM job_evaluation_queue
               WHERE status='queued' AND attempt_count < max_attempts
               ORDER BY priority, eligible_at, queue_id LIMIT ?""",
            (limit,),
        ).fetchall()
        ids = [int(row["queue_id"]) for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"""UPDATE job_evaluation_queue SET status='claimed', lease_owner=?,
                    lease_expires_at=datetime('now', ?), claimed_at=CURRENT_TIMESTAMP,
                    attempt_count=attempt_count+1, updated_at=CURRENT_TIMESTAMP
                    WHERE queue_id IN ({placeholders}) AND status='queued'""",
                (worker_id, f"+{lease_seconds} seconds", *ids),
            )
        result = [_item(row) for row in conn.execute(
            f"SELECT * FROM job_evaluation_queue WHERE queue_id IN ({','.join('?' for _ in ids)}) ORDER BY priority, eligible_at, queue_id" if ids else "SELECT * FROM job_evaluation_queue WHERE 0",
            ids,
        ).fetchall()]
        if owned:
            conn.commit()
        return result
    except Exception:
        if owned:
            conn.rollback()
        raise
    finally:
        if owned:
            conn.close()


def release_stale_claims(*, connection=None) -> int:
    conn, owned = _with_connection(connection)
    try:
        cursor = conn.execute(
            """UPDATE job_evaluation_queue SET status='queued', lease_owner=NULL,
               lease_expires_at=NULL, claimed_at=NULL, updated_at=CURRENT_TIMESTAMP
               WHERE status='claimed' AND datetime(lease_expires_at) <= datetime('now')"""
        )
        if owned:
            conn.commit()
        return cursor.rowcount
    finally:
        if owned:
            conn.close()


def complete_job(queue_id: int, *, connection=None) -> bool:
    conn, owned = _with_connection(connection)
    try:
        cursor = conn.execute(
            """UPDATE job_evaluation_queue SET status='completed', completed_at=CURRENT_TIMESTAMP,
               lease_owner=NULL, lease_expires_at=NULL, last_error=NULL, updated_at=CURRENT_TIMESTAMP
               WHERE queue_id=? AND status='claimed'""",
            (queue_id,),
        )
        if owned:
            conn.commit()
        return cursor.rowcount == 1
    finally:
        if owned:
            conn.close()


def fail_job(queue_id: int, error: str, *, connection=None) -> bool:
    conn, owned = _with_connection(connection)
    try:
        cursor = conn.execute(
            """UPDATE job_evaluation_queue SET status='failed', last_error=?,
               lease_owner=NULL, lease_expires_at=NULL, updated_at=CURRENT_TIMESTAMP
               WHERE queue_id=? AND status IN ('claimed','queued')""",
            (error, queue_id),
        )
        if owned:
            conn.commit()
        return cursor.rowcount == 1
    finally:
        if owned:
            conn.close()


def retry_job(queue_id: int, *, connection=None) -> bool:
    conn, owned = _with_connection(connection)
    try:
        cursor = conn.execute(
            """UPDATE job_evaluation_queue SET status='queued', last_error=NULL,
               eligible_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
               WHERE queue_id=? AND status='failed' AND attempt_count < max_attempts""",
            (queue_id,),
        )
        if owned:
            conn.commit()
        return cursor.rowcount == 1
    finally:
        if owned:
            conn.close()


def cancel_job(job_id: int, reason: str, *, connection=None) -> bool:
    conn, owned = _with_connection(connection)
    try:
        cursor = conn.execute(
            """UPDATE job_evaluation_queue SET status='cancelled', defer_reason=?,
               lease_owner=NULL, lease_expires_at=NULL, updated_at=CURRENT_TIMESTAMP
               WHERE job_id=? AND status NOT IN ('completed','cancelled')""",
            (reason, job_id),
        )
        if owned:
            conn.commit()
        return cursor.rowcount == 1
    finally:
        if owned:
            conn.close()


def queue_summary(*, connection=None) -> dict[str, int]:
    conn, owned = _with_connection(connection)
    try:
        return {row["status"]: int(row["count"]) for row in conn.execute(
            "SELECT status, count(*) AS count FROM job_evaluation_queue GROUP BY status"
        )}
    finally:
        if owned:
            conn.close()
