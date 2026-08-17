from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.migrate import apply_migrations
from src.orchestration.job_evaluation_queue import (
    claim_batch,
    complete_job,
    enqueue_job,
    fail_job,
    release_stale_claims,
    retry_job,
)


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


def test_enqueue_promotes_deferred_job_without_duplication() -> None:
    connection = _connection()
    apply_migrations(connection)
    connection.execute("INSERT INTO job_postings (job_id, company_id, title) VALUES (1, 1, 'ML Scientist')")

    first = enqueue_job(1, description_ready=False, connection=connection)
    second = enqueue_job(1, description_ready=True, connection=connection)

    assert first.status == "deferred"
    assert second.status == "queued"
    assert connection.execute("SELECT count(*) FROM job_evaluation_queue").fetchone()[0] == 1


def test_claim_is_exclusive_and_stale_claim_is_recoverable() -> None:
    connection = _connection()
    apply_migrations(connection)
    connection.execute("INSERT INTO job_postings (job_id, company_id, title) VALUES (1, 1, 'ML Scientist')")
    enqueue_job(1, description_ready=True, connection=connection)

    claimed = claim_batch(run_id="run-1", worker_id="worker-a", limit=1, lease_seconds=300, connection=connection)
    assert [item.job_id for item in claimed] == [1]
    assert claim_batch(run_id="run-2", worker_id="worker-b", limit=1, lease_seconds=300, connection=connection) == []

    connection.execute("UPDATE job_evaluation_queue SET lease_expires_at = datetime('now', '-1 minute') WHERE job_id = 1")
    assert release_stale_claims(connection=connection) == 1
    assert [item.job_id for item in claim_batch(run_id="run-2", worker_id="worker-b", limit=1, lease_seconds=300, connection=connection)] == [1]


def test_completion_is_idempotent_and_retry_is_bounded() -> None:
    connection = _connection()
    apply_migrations(connection)
    connection.execute("INSERT INTO job_postings (job_id, company_id, title) VALUES (1, 1, 'ML Scientist')")
    item = enqueue_job(1, description_ready=True, connection=connection)
    claim_batch(run_id="run-1", worker_id="worker-a", limit=1, lease_seconds=300, connection=connection)

    assert complete_job(item.queue_id, connection=connection) is True
    assert complete_job(item.queue_id, connection=connection) is False
    enqueue_job(1, description_ready=True, reactivate=True, connection=connection)
    claim_batch(run_id="run-2", worker_id="worker-a", limit=1, lease_seconds=300, connection=connection)
    fail_job(item.queue_id, "bad output", connection=connection)
    assert retry_job(item.queue_id, connection=connection) is True
    connection.execute("UPDATE job_evaluation_queue SET attempt_count=max_attempts WHERE queue_id=?", (item.queue_id,))
    fail_job(item.queue_id, "bad again", connection=connection)
    assert retry_job(item.queue_id, connection=connection) is False
