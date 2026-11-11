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


def claim_next_application(worker_id: str, lease_seconds: int = 900, *, run_id: int | None = None, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    if not worker_id.strip() or lease_seconds <= 0:
        raise ValueError("Worker ID and positive lease are required")
    db, owned = _connection(connection)
    try:
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        now = _now()
        # A committed attempt may already have reached the employer before death.
        db.execute(
            """UPDATE application_runs SET status='submission_uncertain',
            pause_reason='Verify employer receipt before reconciliation',
            lease_owner=NULL, lease_expires_at=NULL, updated_at=?
            WHERE status='submitting' AND (lease_expires_at IS NULL OR lease_expires_at<=?)""",
            (now, now),
        )
        row = db.execute(
            """SELECT run_id, status FROM application_runs
               WHERE status IN ('queued','inspecting','preparing','filling')
                 AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                 AND (? IS NULL OR run_id=?)
               ORDER BY created_at, run_id LIMIT 1""",
            (now, run_id, run_id),
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


def transition_application(run_id: int, status: str, *, pause_reason: str | None = None, checkpoint: dict | None = None, expected_owner: str | None = None, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
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
               updated_at=? WHERE run_id=? AND status=?
               AND (? IS NULL OR (lease_owner=? AND lease_expires_at>?))""",
            (status, pause_reason, json.dumps(checkpoint if checkpoint is not None else current["checkpoint"]),
             status, now, status, status, now, run_id, current["status"], expected_owner, expected_owner, now),
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
        if current["status"] in TERMINAL or current["submission_attempted_at"]:
            raise ValueError("Attempted or terminal application run cannot change mode")
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


def approve_answer(run_id: int, field_key: str, answer: str) -> dict[str, Any]:
    """User approval of a staged draft; Python alone updates the field."""
    from src.applications.answer_agent import answer_path
    from src.applications.answer_models import AnswerDraft

    value = answer.strip()
    if not value:
        raise ValueError("Approved answer cannot be blank")
    path = answer_path(run_id, field_key)
    if not path.is_file():
        raise ValueError("No staged draft exists for this field")
    try:
        draft = AnswerDraft.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("Staged answer is invalid") from exc
    if draft.field_key != field_key:
        raise ValueError("Staged answer field does not match")
    db = get_connection()
    try:
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        run = _row(db, run_id)
        if run["status"] in TERMINAL:
            raise ValueError("Terminal application run cannot approve answers")
        cursor = db.execute(
            """UPDATE application_fields SET value=?, status='reviewed', disposition='provided',
               validation_error=NULL, updated_at=? WHERE job_id=? AND field_key=?""",
            (value, _now(), run["job_id"], field_key),
        )
        if cursor.rowcount != 1:
            raise ValueError("Application field not found")
        db.execute(
            """INSERT INTO application_audit_events (job_id, event_type, target_key, outcome, details_json)
               VALUES (?, 'answer_approved', ?, 'success', '{}')""",
            (run["job_id"], field_key),
        )
        result = dict(db.execute(
            "SELECT * FROM application_fields WHERE job_id=? AND field_key=?",
            (run["job_id"], field_key),
        ).fetchone())
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def read_application_run(run_id: int) -> dict[str, Any]:
    db = get_connection()
    try:
        return _row(db, run_id)
    finally:
        db.close()


def resume_application(run_id: int) -> dict[str, Any]:
    """Explicit user release of a pause, preserving all durable work."""
    db = get_connection()
    try:
        db.execute('BEGIN IMMEDIATE')
        if _row(db, run_id)['status'] != 'needs_user':
            raise ValueError('Only a needs_user run can resume')
        result = transition_application(run_id, 'queued', connection=db)
        db.commit()
        return result
    finally:
        db.close()


def get_review_packet(run_id: int) -> dict[str, Any]:
    from src.database.application_workspace import get_application_workspace
    from src.database.application_preparation import list_application_steps
    from src.applications.answer_agent import answer_path
    run = read_application_run(run_id)
    session, fields = get_application_workspace(run['job_id'])
    db = get_connection()
    try:
        job = dict(db.execute('SELECT * FROM job_postings WHERE job_id=?', (run['job_id'],)).fetchone())
    finally:
        db.close()
    drafts = {}
    for field in fields:
        path = answer_path(run_id, field['field_key'])
        if path.is_file():
            try:
                drafts[field['field_key']] = json.loads(path.read_text())
            except (ValueError, OSError):
                drafts[field['field_key']] = {'error': 'Draft unavailable'}
    return {'run': run, 'job': job, 'session': session, 'fields': fields,
            'artifacts': run['checkpoint'].get('artifacts', {}), 'drafts': drafts,
            'pages': run['checkpoint'].get('pages', []),
            'validation': run['checkpoint'].get('validation', []),
            'remaining': [f['field_key'] for f in fields if f['required'] and f['disposition'] != 'provided'],
            'steps': list_application_steps(run['job_id'])}


def renew_application_lease(run_id: int, worker_id: str, lease_seconds: int = 900) -> bool:
    """Renew only live ownership; an expired lease may already belong elsewhere."""
    if lease_seconds <= 0:
        raise ValueError('Positive lease duration required')
    db = get_connection()
    try:
        now = _now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        cursor = db.execute(
            """UPDATE application_runs SET lease_expires_at=? WHERE run_id=? AND lease_owner=?
               AND lease_expires_at>? AND status IN ('inspecting','preparing','filling')""",
            (expires, run_id, worker_id, now),
        )
        db.commit()
        return cursor.rowcount == 1
    finally:
        db.close()


def release_application_claim(run_id: int, worker_id: str) -> None:
    """Return pre-submit work to the queue without touching another owner's claim."""
    db = get_connection()
    try:
        db.execute(
            """UPDATE application_runs SET status='queued', lease_owner=NULL, lease_expires_at=NULL,
               updated_at=? WHERE run_id=? AND lease_owner=?
               AND status IN ('inspecting','preparing','filling')""", (_now(), run_id, worker_id),
        )
        db.commit()
    finally:
        db.close()
