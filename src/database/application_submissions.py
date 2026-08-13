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
