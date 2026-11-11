"""Immutable snapshots for applications confirmed as submitted by the user."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.database.db import get_connection
from src.database.migrate import apply_migrations


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["snapshot"] = json.loads(result.pop("snapshot_json"))
    return result


def record_application_submission(
    job_id: int,
    *,
    method: str = "user_confirmed_external",
) -> dict[str, Any]:
    """Snapshot reviewed local data and atomically move a tracked job to Applied."""
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        session_row = connection.execute(
            "SELECT * FROM application_sessions WHERE job_id = ?;", (job_id,)
        ).fetchone()
        if session_row is None:
            raise ValueError("Inspect or create an application workspace before recording submission.")
        session = dict(session_row)
        fields = [dict(row) for row in connection.execute(
            "SELECT * FROM application_fields WHERE job_id = ? ORDER BY section, position, field_id;",
            (job_id,),
        ).fetchall()]
        facts = [dict(row) for row in connection.execute(
            "SELECT * FROM application_facts ORDER BY label;"
        ).fetchall()]
        submitted_at = _now()
        snapshot = {
            "contact_details": [row for row in fields if row["section"] == "contact_details"],
            "documents": [row for row in fields if row["section"] in {"resume", "cover_letter", "additional_documents"}],
            "questions": facts,
            "application_fields": [row for row in fields if row["section"] == "questions"],
        }
        cursor = connection.execute(
            """INSERT INTO application_submissions
            (job_id, provider, application_url, method, snapshot_json, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?);""",
            (job_id, session.get("provider"), session.get("application_url"), method, json.dumps(snapshot), submitted_at),
        )
        connection.execute(
            """UPDATE tracked_jobs SET stage = 'applied',
            applied_at = COALESCE(applied_at, ?), updated_at = ? WHERE job_id = ?;""",
            (submitted_at, submitted_at, job_id),
        )
        connection.execute(
            """INSERT INTO application_stage_history (job_id, stage, entered_at)
            VALUES (?, 'applied', ?);""",
            (job_id, submitted_at),
        )
        connection.execute(
            """UPDATE application_sessions SET status = 'submitted', current_page = 'success',
            updated_at = ? WHERE job_id = ?;""",
            (submitted_at, job_id),
        )
        connection.execute(
            """INSERT INTO application_audit_events
            (job_id, provider, event_type, outcome, details_json)
            VALUES (?, ?, 'submission_reconciled', 'success', ?);""",
            (job_id, session.get("provider"), json.dumps({"method": method, "submission_id": cursor.lastrowid})),
        )
        for row in connection.execute(
            "SELECT run_id, checkpoint_json FROM application_runs WHERE job_id=? AND status NOT IN ('submitted','failed','cancelled')",
            (job_id,),
        ).fetchall():
            checkpoint = json.loads(row['checkpoint_json'] or '{}')
            checkpoint['submission_id'] = cursor.lastrowid
            connection.execute(
                """UPDATE application_runs SET status='submitted', checkpoint_json=?,
                pause_reason=NULL, lease_owner=NULL, lease_expires_at=NULL, updated_at=? WHERE run_id=?""",
                (json.dumps(checkpoint), submitted_at, row['run_id']),
            )
        connection.commit()
        return get_application_submission(int(cursor.lastrowid)) or {}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_application_submission(submission_id: int) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        return _decode(connection.execute(
            "SELECT * FROM application_submissions WHERE submission_id = ?;", (submission_id,)
        ).fetchone())
    finally:
        connection.close()


def get_latest_application_submission(job_id: int) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        return _decode(connection.execute(
            """SELECT * FROM application_submissions WHERE job_id = ?
            ORDER BY submitted_at DESC, submission_id DESC LIMIT 1;""",
            (job_id,),
        ).fetchone())
    finally:
        connection.close()


def record_confirmed_application_submission(run_id: int, receipt: dict, *, connection=None) -> dict:
    """Commit receipt, immutable attempted payload, run, and Applied milestone together."""
    from src.database.application_runs import _row
    owned = connection is None
    db = connection or get_connection()
    try:
        if not db.in_transaction:
            db.execute('BEGIN IMMEDIATE')
        db.execute('SAVEPOINT confirmed_submission')
        run = _row(db, run_id)
        checkpoint = run['checkpoint']
        if run['status'] == 'submitted' and checkpoint.get('submission_id'):
            result = _decode(db.execute('SELECT * FROM application_submissions WHERE submission_id=?', (checkpoint['submission_id'],)).fetchone())
        else:
            if run['status'] not in {'submitting','submission_uncertain'} or not run['submission_attempted_at']:
                raise ValueError('No durable submission attempt')
            if not receipt.get('url') or not receipt.get('acknowledgment'):
                raise ValueError('Employer receipt evidence required')
            snapshot = checkpoint.get('submission_snapshot')
            if not snapshot:
                raise ValueError('Attempted payload snapshot required')
            snapshot = {**snapshot, 'receipt': receipt, 'run_id': run_id}
            session = db.execute('SELECT * FROM application_sessions WHERE job_id=?', (run['job_id'],)).fetchone()
            if session is None:
                raise ValueError('Application session required')
            now = _now()
            cursor = db.execute('INSERT INTO application_submissions(job_id,provider,application_url,method,snapshot_json,submitted_at) VALUES(?,?,?,?,?,?)',
                (run['job_id'],session['provider'],snapshot['application_url'],'worker_confirmed',json.dumps(snapshot),now))
            submission_id = cursor.lastrowid
            if db.execute("UPDATE tracked_jobs SET stage='applied',applied_at=COALESCE(applied_at,?),updated_at=? WHERE job_id=?", (now,now,run['job_id'])).rowcount != 1:
                raise ValueError('Tracked job required')
            db.execute("INSERT INTO application_stage_history(job_id,stage,entered_at) VALUES(?,'applied',?)", (run['job_id'],now))
            db.execute("UPDATE application_sessions SET status='submitted',current_page='success',updated_at=? WHERE job_id=?", (now,run['job_id']))
            checkpoint['submission_id'] = submission_id
            db.execute("UPDATE application_runs SET status='submitted',checkpoint_json=?,lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?", (json.dumps(checkpoint),now,run_id))
            db.execute("INSERT INTO application_audit_events(job_id,event_type,outcome,details_json) VALUES(?,'submission_confirmed','success',?)", (run['job_id'],json.dumps({'run_id':run_id,'submission_id':submission_id})))
            result = _decode(db.execute('SELECT * FROM application_submissions WHERE submission_id=?',(submission_id,)).fetchone())
        db.execute('RELEASE SAVEPOINT confirmed_submission')
        if owned:
            db.commit()
        return result
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT confirmed_submission')
        db.execute('RELEASE SAVEPOINT confirmed_submission')
        if owned:
            db.rollback()
        raise
    finally:
        if owned:
            db.close()
