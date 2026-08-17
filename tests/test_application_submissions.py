from __future__ import annotations

import sqlite3
from pathlib import Path

from src.database.application_submissions import (
    get_latest_application_submission,
    record_application_submission,
)


def _connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def test_submission_snapshots_and_moves_to_applied(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "submissions.db"
    connection = _connection(database)
    connection.executescript(Path("src/database/schema.sql").read_text(encoding="utf-8"))
    connection.execute("INSERT INTO companies (company_id, company_name, website) VALUES (1, 'Example', 'https://example.test')")
    connection.execute("INSERT INTO job_postings (job_id, company_id, title) VALUES (1, 1, 'AI Engineer')")
    connection.execute("INSERT INTO tracked_jobs (job_id, stage) VALUES (1, 'applying')")
    connection.execute("INSERT INTO application_sessions (job_id, application_url, provider) VALUES (1, 'https://apply.test', 'dayforce')")
    connection.execute("""INSERT INTO application_fields
        (job_id, section, field_key, label, value, disposition)
        VALUES (1, 'contact_details', 'email', 'Email', 'me@example.test', 'provided'),
               (1, 'resume', 'resume', 'Resume', '/tmp/resume.docx', 'provided'),
               (1, 'cover_letter', 'cover_letter', 'Cover letter', '/tmp/cover.docx', 'provided');""")
    connection.execute("INSERT INTO application_facts (fact_key, label, value) VALUES ('authorized', 'Authorized', 'yes')")
    connection.commit()
    connection.close()
    monkeypatch.setattr("src.database.application_submissions.get_connection", lambda: _connection(database))

    submission = record_application_submission(1)
    assert submission["snapshot"]["contact_details"][0]["value"] == "me@example.test"
    assert submission["snapshot"]["questions"][0]["value"] == "yes"
    assert get_latest_application_submission(1)["submission_id"] == submission["submission_id"]

    connection = _connection(database)
    tracked = connection.execute("SELECT stage, applied_at FROM tracked_jobs WHERE job_id = 1").fetchone()
    session = connection.execute("SELECT status FROM application_sessions WHERE job_id = 1").fetchone()
    event = connection.execute("SELECT event_type FROM application_audit_events WHERE job_id = 1 ORDER BY event_id DESC").fetchone()
    connection.close()
    assert tracked["stage"] == "applied" and tracked["applied_at"]
    assert session["status"] == "submitted"
    assert event["event_type"] == "submission_reconciled"
