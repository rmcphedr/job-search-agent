from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.migrate import apply_migrations


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema = Path("src/database/schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    connection.execute("INSERT INTO schema_migrations (version) VALUES (10)")
    return connection


def test_migration_adds_evaluation_queue_and_telemetry_tables() -> None:
    connection = _connection()

    changes = apply_migrations(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "job_evaluation_queue",
        "job_evaluation_runs",
        "job_evaluation_attempts",
    } <= tables
    assert "schema_migrations.version=11" in changes


def test_queue_enforces_one_item_per_job_and_valid_status() -> None:
    connection = _connection()
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO job_postings (job_id, company_id, title) VALUES (1, 1, 'ML Scientist')"
    )
    connection.execute(
        "INSERT INTO job_evaluation_queue (job_id, status) VALUES (1, 'queued')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO job_evaluation_queue (job_id, status) VALUES (1, 'queued')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO job_evaluation_queue (job_id, status) VALUES (2, 'unknown')"
        )


def test_attempt_enforces_usage_provenance() -> None:
    connection = _connection()
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO job_postings (job_id, company_id, title) VALUES (1, 1, 'ML Scientist')"
    )
    connection.execute(
        "INSERT INTO job_evaluation_queue (queue_id, job_id, status) VALUES (1, 1, 'queued')"
    )
    connection.execute(
        "INSERT INTO job_evaluation_runs (run_id, status) VALUES ('run-1', 'running')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO job_evaluation_attempts
               (run_id, queue_id, job_id, model, reasoning_effort, status, usage_provenance)
               VALUES ('run-1', 1, 1, 'gpt-5.6-terra', 'low', 'running', 'guessed')"""
        )
