from __future__ import annotations

import sqlite3
from pathlib import Path

from src.database.application_automation import (
    application_readiness,
    classify_application,
    list_application_events,
    list_application_facts,
    record_application_event,
    save_application_fact,
    set_field_observation,
)
from src.database.migrate import apply_migrations


def _connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "automation.db"
    connection = _connection(path)
    connection.executescript(Path("src/database/schema.sql").read_text(encoding="utf-8"))
    connection.execute("INSERT INTO companies VALUES (1, 'Example', 'https://example.test', NULL, NULL, NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
    connection.execute("INSERT INTO job_postings (job_id, company_id, title) VALUES (1, 1, 'AI Engineer')")
    connection.execute(
        """INSERT INTO application_fields (job_id, section, field_key, label, required, value, disposition)
        VALUES (1, 'questions', 'authorized', 'Authorized', 1, 'Yes', 'provided'),
               (1, 'questions', 'salary', 'Salary', 0, NULL, 'pending');"""
    )
    connection.commit()
    connection.close()
    return path


def test_facts_audit_readiness_and_validation(monkeypatch, tmp_path: Path) -> None:
    database = _database(tmp_path)
    monkeypatch.setattr("src.database.application_automation.get_connection", lambda: _connection(database))

    save_application_fact("authorized_canada", "Authorized in Canada", "yes", value_type="boolean")
    assert list_application_facts()[0]["source"] == "user_confirmed"
    record_application_event("questionnaire_answered", job_id=1, target_key="authorized")
    assert list_application_events(1)[0]["event_type"] == "questionnaire_answered"

    readiness = application_readiness(1)
    assert readiness["ready"]
    assert readiness["optional_missing"] == ["Salary"]
    set_field_observation(1, "salary", validation_error="Invalid amount", disposition="provided")
    assert application_readiness(1)["validation_errors"][0]["field"] == "Salary"


def test_classification_respects_human_gates() -> None:
    assert classify_application("dayforce", captcha=True, consent=False, requires_account=False)[0] == "assisted"
    assert classify_application("dayforce", captcha=False, consent=False, requires_account=False)[0] == "automatable"
    assert classify_application("generic_web_form", captcha=False, consent=False, requires_account=False)[0] == "automatable"
    assert classify_application("unknown", captcha=False, consent=False, requires_account=False)[0] == "manual"


def test_migration_adds_automation_schema(tmp_path: Path) -> None:
    database = tmp_path / "migrate.db"
    connection = _connection(database)
    connection.executescript(Path("src/database/schema.sql").read_text(encoding="utf-8"))
    changes = apply_migrations(connection)
    connection.commit()
    tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    connection.close()
    assert "application_facts" in tables
    assert "application_audit_events" in tables
