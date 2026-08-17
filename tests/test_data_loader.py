"""Focused tests for uncached dashboard record loading."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.ui.data_loader import get_current_job_by_id


@pytest.fixture()
def jobs_db(tmp_path: Path) -> Path:
    database = tmp_path / "jobs.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE companies (
            company_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL
        );
        CREATE TABLE job_postings (
            job_id INTEGER PRIMARY KEY,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            location TEXT,
            source_board TEXT,
            keyword_score REAL,
            matched_keywords TEXT,
            fit_score REAL,
            fit_reason TEXT,
            fit_details TEXT,
            evaluated_at TEXT,
            date_found TEXT,
            active INTEGER,
            url TEXT,
            description TEXT,
            description_status TEXT,
            description_source TEXT,
            description_source_url TEXT,
            description_checked_at TEXT,
            description_error TEXT
        );
        INSERT INTO companies (company_id, company_name)
        VALUES (1, 'Thales');
        INSERT INTO job_postings (
            job_id, company_id, title, location, active, url, description
        ) VALUES (
            705,
            1,
            'Applied AI Research Scientist',
            'Montreal, QC (Hybrid)',
            1,
            'https://example.com/thales/705',
            'Saved Thales job description'
        );
        """
    )
    connection.commit()
    connection.close()
    return database


def test_current_job_lookup_reads_selected_posting_directly(
    jobs_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.ui.data_loader.get_connection",
        lambda: _connect(jobs_db),
    )

    job = get_current_job_by_id("705")

    assert job is not None
    assert job["job_id"] == 705
    assert job["company_name"] == "Thales"
    assert job["title"] == "Applied AI Research Scientist"
    assert job["description"] == "Saved Thales job description"


@pytest.mark.parametrize("job_id", ["missing", "", 999])
def test_current_job_lookup_returns_none_for_invalid_or_absent_id(
    jobs_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_id: int | str,
) -> None:
    monkeypatch.setattr(
        "src.ui.data_loader.get_connection",
        lambda: _connect(jobs_db),
    )

    assert get_current_job_by_id(job_id) is None


def _connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection
