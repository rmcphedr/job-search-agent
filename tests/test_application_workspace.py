from __future__ import annotations

import sqlite3
from pathlib import Path

from src.applications.dayforce import parse_dayforce_application
from src.database.application_workspace import (
    get_application_workspace,
    prefill_generated_cover_letter,
    prefill_from_master_profile,
    save_inspection,
    update_application_field,
)


DAYFORCE_HTML = """
<html><body>
  <h1>AI Engineer</h1><h1>Candidate Info</h1>
  <input id="email" aria-label="Email Address *" aria-required="true">
  <input id="first" aria-label="First Name *" aria-required="true">
  <input id="linkedin" aria-label="LinkedIn Profile">
  <button>Import Resume</button>
  <h2>Cover Letter</h2><button>Add Cover Letter</button>
  <h2>Additional Documents</h2><button>Add Additional Documents</button>
  <input type="checkbox" aria-label="I agree to the Privacy Statement">
  <iframe title="reCAPTCHA"></iframe>
</body></html>
"""


def _connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "jobs.db"
    connection = _connection(path)
    connection.executescript(Path("src/database/schema.sql").read_text(encoding="utf-8"))
    connection.execute("INSERT INTO companies (company_id, company_name, website) VALUES (1, 'TML', 'https://example.test')")
    connection.execute("INSERT INTO job_postings (job_id, company_id, title) VALUES (1, 1, 'AI Engineer')")
    connection.commit()
    connection.close()
    return path


def test_dayforce_inspection_detects_fields_documents_and_gates() -> None:
    inspection = parse_dayforce_application(DAYFORCE_HTML, "https://jobs.dayforcehcm.com/example")
    keys = {field.field_key for field in inspection.fields}
    assert {"email_address", "first_name", "linkedin_profile", "resume", "cover_letter"} <= keys
    assert next(field for field in inspection.fields if field.field_key == "email_address").required
    assert inspection.privacy_consent_required
    assert inspection.captcha_required
    assert not inspection.requires_account


def test_workspace_round_trip_preserves_reviewed_value(monkeypatch, tmp_path: Path) -> None:
    database = _database(tmp_path)

    def connect() -> sqlite3.Connection:
        return _connection(database)

    monkeypatch.setattr("src.database.application_workspace.get_connection", connect)
    inspection = parse_dayforce_application(DAYFORCE_HTML, "https://jobs.dayforcehcm.com/example")
    save_inspection(1, inspection)
    update_application_field(1, "email_address", "candidate@example.com")
    session, fields = get_application_workspace(1)

    assert session and session["provider"] == "dayforce"
    email = next(field for field in fields if field["field_key"] == "email_address")
    assert email["value"] == "candidate@example.com"
    assert email["status"] == "reviewed"


def test_profile_prefill_does_not_overwrite_reviewed_value(monkeypatch, tmp_path: Path) -> None:
    database = _database(tmp_path)

    def connect() -> sqlite3.Connection:
        return _connection(database)

    monkeypatch.setattr("src.database.application_workspace.get_connection", connect)
    inspection = parse_dayforce_application(DAYFORCE_HTML, "https://jobs.dayforcehcm.com/example")
    save_inspection(1, inspection)
    update_application_field(1, "email_address", "reviewed@example.com")
    profile = tmp_path / "profile.md"
    profile.write_text(
        "- **Name:** Ryan McPhedrain, PhD\n"
        "- **Email:** profile@example.com\n"
        "- **Phone:** 555-0100\n"
        "- **Location:** Montreal, QC, Canada\n"
        "- **LinkedIn:** https://linkedin.com/in/example\n",
        encoding="utf-8",
    )

    prefill_from_master_profile(1, profile)
    _, fields = get_application_workspace(1)

    values = {field["field_key"]: field["value"] for field in fields}
    assert values["email_address"] == "reviewed@example.com"
    assert values["first_name"] == "Ryan"
    assert values["linkedin_profile"] == "https://linkedin.com/in/example"


def test_completed_cover_letter_prefills_empty_workspace_field(monkeypatch, tmp_path: Path) -> None:
    database = _database(tmp_path)

    def connect() -> sqlite3.Connection:
        return _connection(database)

    monkeypatch.setattr("src.database.application_workspace.get_connection", connect)
    inspection = parse_dayforce_application(DAYFORCE_HTML, "https://jobs.dayforcehcm.com/example")
    save_inspection(1, inspection)
    document = tmp_path / "cover-letter.docx"
    document.write_bytes(b"docx")
    connection = connect()
    connection.execute(
        """
        INSERT INTO application_preparation_steps
            (job_id, step_key, title, position, status, details)
        VALUES (1, 'cover_letter', 'Cover letter', 5, 'complete', ?);
        """,
        (f"Cover letter DOCX: {document}",),
    )
    connection.commit()
    connection.close()

    assert prefill_generated_cover_letter(1)
    _, fields = get_application_workspace(1)
    cover_letter = next(field for field in fields if field["field_key"] == "cover_letter")
    assert cover_letter["value"] == str(document)
    assert cover_letter["status"] == "draft"
