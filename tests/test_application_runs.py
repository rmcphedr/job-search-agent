"""Durable, single-job application-run lifecycle."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.application_runs import (
    cancel_application,
    claim_next_application,
    enqueue_application,
    get_application_run,
    set_application_mode,
    transition_application,
)
from src.database.application_preparation import STEP_DEFINITIONS
from src.database.db import SCHEMA_FILE
from src.database.migrate import apply_migrations


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "runs.db"
    with _connect(path) as connection:
        connection.executescript(SCHEMA_FILE.read_text())
        connection.execute("INSERT INTO companies (company_id, company_name, website) VALUES (1, 'Example', 'https://example.test')")
        connection.executemany(
            "INSERT INTO job_postings (job_id, company_id, title, active, description_status) VALUES (?, 1, 'Engineer', ?, ?)",
            [(10, 1, 'enriched'), (11, 1, 'enriched'), (12, 0, 'expired')],
        )
    return path


def test_enqueues_either_mode_once_and_rejects_duplicate_active_run(db: Path) -> None:
    with _connect(db) as connection:
        first = enqueue_application(10, "fully_automate", connection=connection)
        second = enqueue_application(11, "draft_for_review", connection=connection)
        assert first["mode"] == "fully_automate"
        assert second["mode"] == "draft_for_review"
        assert first["status"] == second["status"] == "queued"
        assert connection.execute("SELECT stage FROM tracked_jobs WHERE job_id=10").fetchone()[0] == "applying"
        assert connection.execute("SELECT COUNT(*) FROM application_preparation_steps WHERE job_id=10").fetchone()[0] == len(STEP_DEFINITIONS)
        with pytest.raises(ValueError, match="active run"):
            enqueue_application(10, "draft_for_review", connection=connection)
        with pytest.raises(ValueError, match="not active"):
            enqueue_application(12, "fully_automate", connection=connection)
        with pytest.raises(ValueError, match="not found"):
            enqueue_application(999, "fully_automate", connection=connection)
        assert connection.execute("SELECT COUNT(*) FROM tracked_jobs WHERE job_id=12").fetchone()[0] == 0


def test_claim_is_exclusive_and_expired_lease_recovers(db: Path) -> None:
    with _connect(db) as connection:
        run = enqueue_application(10, "fully_automate", connection=connection)
        claimed = claim_next_application("worker-a", lease_seconds=30, connection=connection)
        assert claimed["run_id"] == run["run_id"]
        assert claimed["lease_owner"] == "worker-a"
        assert claimed["status"] == "inspecting"
        assert claimed["attempt_count"] == 1
        assert claim_next_application("worker-b", connection=connection) is None
        connection.execute("UPDATE application_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE run_id=?", (run["run_id"],))
        recovered = claim_next_application("worker-b", connection=connection)
        assert recovered["run_id"] == run["run_id"]
        assert recovered["lease_owner"] == "worker-b"
        assert recovered["attempt_count"] == 2
        transition_application(run["run_id"], "submission_uncertain", connection=connection)
        assert claim_next_application("worker-c", connection=connection) is None


def test_mode_change_requires_explicit_call_and_cancel_stops_claim(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.database.application_runs.get_connection", lambda: _connect(db))
    run = enqueue_application(10, "draft_for_review")
    transition_application(run["run_id"], "ready_for_review", checkpoint={"page": 2})
    assert get_application_run(10)["mode"] == "draft_for_review"
    assert get_application_run(10)["checkpoint"] == {"page": 2}
    changed = set_application_mode(run["run_id"], "fully_automate")
    assert changed["mode"] == "fully_automate"
    cancelled = cancel_application(run["run_id"])
    assert cancelled["status"] == "cancelled"
    assert claim_next_application("worker") is None


def test_migration_adds_runs_without_enrolling_historical_jobs(tmp_path: Path) -> None:
    path = tmp_path / "historical.db"
    with _connect(path) as connection:
        connection.executescript(SCHEMA_FILE.read_text())
        connection.execute("DROP TABLE application_runs")
        connection.execute("INSERT INTO companies (company_id, company_name, website) VALUES (1, 'Example', 'https://example.test')")
        connection.execute("INSERT INTO job_postings (job_id, company_id, title) VALUES (10, 1, 'Engineer')")
        connection.execute("INSERT INTO tracked_jobs (job_id, stage) VALUES (10, 'applying')")
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO schema_migrations (version) VALUES (12)")
        apply_migrations(connection)
        assert connection.execute("SELECT COUNT(*) FROM application_runs").fetchone()[0] == 0
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 13


def test_enqueue_rolls_back_tracking_when_preparation_fails(db: Path) -> None:
    with _connect(db) as connection:
        connection.execute(
            """CREATE TRIGGER reject_preparation BEFORE INSERT ON application_preparation_steps
            BEGIN SELECT RAISE(ABORT, 'preparation unavailable'); END"""
        )
        with pytest.raises(sqlite3.IntegrityError, match="preparation unavailable"):
            enqueue_application(10, "fully_automate", connection=connection)
    with _connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM application_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM tracked_jobs").fetchone()[0] == 0
