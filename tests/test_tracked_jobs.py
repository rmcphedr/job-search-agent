"""Tests for tracked job application storage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.tracked_jobs import (
    list_tracked_jobs,
    track_job,
    track_jobs,
    untrack_job,
    untrack_jobs,
    update_tracked_notes,
    update_tracked_stage,
)


@pytest.fixture()
def tracking_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE companies (
            company_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            website TEXT NOT NULL UNIQUE
        );
        CREATE TABLE job_postings (
            job_id INTEGER PRIMARY KEY,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            location TEXT,
            url TEXT,
            active INTEGER DEFAULT 1,
            fit_score REAL,
            keyword_score REAL,
            FOREIGN KEY (company_id) REFERENCES companies (company_id)
        );
        CREATE TABLE tracked_jobs (
            tracked_id INTEGER PRIMARY KEY,
            job_id INTEGER NOT NULL UNIQUE,
            stage TEXT NOT NULL DEFAULT 'tracked',
            notes TEXT,
            applied_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
        );
        INSERT INTO companies (company_id, company_name, website)
        VALUES (1, 'Example Bio', 'https://example.com');
        INSERT INTO job_postings (job_id, company_id, title, location, url, active)
        VALUES (10, 1, 'ML Scientist', 'Montreal', 'https://example.com/jobs/10', 1);
        """
    )
    connection.commit()
    connection.close()
    return db_path


def test_bulk_track_and_untrack(tracking_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.database.tracked_jobs.get_connection", lambda: _connect(tracking_db))

    assert track_jobs([10, 10]) == 2
    assert len(list_tracked_jobs()) == 1

    assert untrack_jobs([10]) == 1
    assert list_tracked_jobs() == []


def test_track_and_list_job(tracking_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.database.tracked_jobs.get_connection", lambda: _connect(tracking_db))

    created = track_job(10)
    assert created["job_id"] == 10
    assert created["stage"] == "tracked"

    rows = list_tracked_jobs()
    assert len(rows) == 1
    assert rows[0]["title"] == "ML Scientist"
    assert rows[0]["company_name"] == "Example Bio"


def test_update_stage_sets_applied_at(tracking_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.database.tracked_jobs.get_connection", lambda: _connect(tracking_db))
    track_job(10)

    updated = update_tracked_stage(10, "applied")
    assert updated is not None
    assert updated["stage"] == "applied"
    assert updated["applied_at"] is not None


def test_notes_and_untrack(tracking_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.database.tracked_jobs.get_connection", lambda: _connect(tracking_db))
    track_job(10)

    updated = update_tracked_notes(10, "Follow up next week")
    assert updated is not None
    assert updated["notes"] == "Follow up next week"

    assert untrack_job(10) is True
    assert list_tracked_jobs() == []


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection
