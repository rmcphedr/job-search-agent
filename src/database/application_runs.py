"""Durable application runs and their transactional enqueue boundary."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from src.database.application_preparation import STEP_DEFINITIONS
from src.database.db import get_connection

MODES = frozenset({"fully_automate", "draft_for_review"})
STATUSES = frozenset({
    "queued", "inspecting", "preparing", "filling", "needs_user",
    "ready_for_review", "submitting", "submitted", "submission_uncertain",
    "failed", "cancelled",
})
TERMINAL = frozenset({"submitted", "failed", "cancelled"})
CLAIMABLE = ("queued", "inspecting", "preparing", "filling")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(connection: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM application_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"Application run {run_id} not found")
    result = dict(row)
    result["checkpoint"] = json.loads(result.pop("checkpoint_json") or "{}")
    return result


def _connection(connection: sqlite3.Connection | None) -> tuple[sqlite3.Connection, bool]:
    if connection is None:
        return get_connection(), True
    return connection, False


def enqueue_application(job_id: int, mode: str, *, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"Invalid application mode: {mode}")
    db, owned = _connection(connection)
    savepoint_started = False
    try:
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        db.execute("SAVEPOINT enqueue_application")
        savepoint_started = True
        job = db.execute("SELECT active, description_status FROM job_postings WHERE job_id=?", (job_id,)).fetchone()
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        if not job["active"] or job["description_status"] == "expired":
            raise ValueError(f"Job {job_id} is not active")
        existing = db.execute(
            "SELECT 1 FROM application_runs WHERE job_id=? AND status NOT IN ('submitted','failed','cancelled')",
            (job_id,),
        ).fetchone()
        if existing:
            raise ValueError(f"Job {job_id} already has an active run")
        now = _now()
        cursor = db.execute(
            "INSERT INTO application_runs (job_id, mode, status, checkpoint_json, created_at, updated_at) VALUES (?, ?, 'queued', '{}', ?, ?)",
            (job_id, mode, now, now),
        )
        db.execute(
            "INSERT OR IGNORE INTO tracked_jobs (job_id, stage, created_at, updated_at) VALUES (?, 'applying', ?, ?)",
            (job_id, now, now),
        )
        db.execute("UPDATE tracked_jobs SET stage='applying', updated_at=? WHERE job_id=?", (now, job_id))
        for position, (key, title) in enumerate(STEP_DEFINITIONS, 1):
            db.execute(
                "INSERT OR IGNORE INTO application_preparation_steps (job_id, step_key, title, position, status, updated_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (job_id, key, title, position, now),
            )
        result = _row(db, int(cursor.lastrowid))
        db.execute("RELEASE SAVEPOINT enqueue_application")
        savepoint_started = False
        if owned:
            db.commit()
        return result
    except Exception:
        if savepoint_started:
            db.execute("ROLLBACK TO SAVEPOINT enqueue_application")
            db.execute("RELEASE SAVEPOINT enqueue_application")
        if owned:
            db.rollback()
        raise
    finally:
        if owned:
            db.close()


def claim_next_application(worker_id: str, lease_seconds: int = 900, *, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    if not worker_id.strip() or lease_seconds <= 0:
        raise ValueError("Worker ID and positive lease are required")
    db, owned = _connection(connection)
    try:
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        now = _now()
        row = db.execute(
            """SELECT run_id, status FROM application_runs
               WHERE status IN ('queued','inspecting','preparing','filling')
                 AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
               ORDER BY created_at, run_id LIMIT 1""",
            (now,),
        ).fetchone()
        if row is None:
            if owned:
                db.commit()
            return None
        run_id = int(row["run_id"])
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        db.execute(
            """UPDATE application_runs SET status=?, lease_owner=?, lease_expires_at=?,
               attempt_count=attempt_count+1, claimed_at=?, updated_at=? WHERE run_id=?""",
            ("inspecting" if row["status"] == "queued" else row["status"], worker_id, expires, now, now, run_id),
        )
        result = _row(db, run_id)
        if owned:
            db.commit()
        return result
    except Exception:
        if owned:
            db.rollback()
        raise
    finally:
        if owned:
            db.close()


def transition_application(run_id: int, status: str, *, pause_reason: str | None = None, checkpoint: dict | None = None, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"Invalid application status: {status}")
    db, owned = _connection(connection)
    try:
        current = _row(db, run_id)
        if current["status"] in TERMINAL:
            raise ValueError("Terminal application run cannot transition")
        now = _now()
        cursor = db.execute(
            """UPDATE application_runs SET status=?, pause_reason=?, checkpoint_json=?,
               submission_attempted_at=CASE WHEN ?='submitting' THEN COALESCE(submission_attempted_at, ?) ELSE submission_attempted_at END,
               lease_owner=CASE WHEN ? IN ('needs_user','ready_for_review','submission_uncertain','submitted','failed','cancelled') THEN NULL ELSE lease_owner END,
               lease_expires_at=CASE WHEN ? IN ('needs_user','ready_for_review','submission_uncertain','submitted','failed','cancelled') THEN NULL ELSE lease_expires_at END,
               updated_at=? WHERE run_id=? AND status=?""",
            (status, pause_reason, json.dumps(checkpoint if checkpoint is not None else current["checkpoint"]),
             status, now, status, status, now, run_id, current["status"]),
        )
        if cursor.rowcount != 1:
            raise ValueError("Application run changed during transition")
        result = _row(db, run_id)
        if owned:
            db.commit()
        return result
    finally:
        if owned:
            db.close()


def set_application_mode(run_id: int, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"Invalid application mode: {mode}")
    db = get_connection()
    try:
        current = _row(db, run_id)
        if current["status"] in TERMINAL:
            raise ValueError("Terminal application run cannot change mode")
        cursor = db.execute(
            "UPDATE application_runs SET mode=?, updated_at=? WHERE run_id=? AND status=?",
            (mode, _now(), run_id, current["status"]),
        )
        if cursor.rowcount != 1:
            raise ValueError("Application run changed during mode change")
        db.commit()
        return _row(db, run_id)
    finally:
        db.close()


def cancel_application(run_id: int) -> dict[str, Any]:
    return transition_application(run_id, "cancelled")


def get_application_run(job_id: int) -> dict[str, Any] | None:
    db = get_connection()
    try:
        row = db.execute("SELECT run_id FROM application_runs WHERE job_id=? ORDER BY run_id DESC LIMIT 1", (job_id,)).fetchone()
        return _row(db, int(row["run_id"])) if row else None
    finally:
        db.close()
