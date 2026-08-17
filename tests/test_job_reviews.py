"""Tests for quick-review decision persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.job_reviews import get_review_decisions, set_review_decision


@pytest.fixture()
def review_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "review.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE job_postings (
            job_id INTEGER PRIMARY KEY,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL
        );
        INSERT INTO job_postings (job_id, company_id, title)
        VALUES (10, 1, 'ML Scientist');
        """
    )
    connection.commit()
    connection.close()
    return db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def test_review_decision_is_created_and_replaced(review_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.database.job_reviews.get_connection", lambda: _connect(review_db))

    set_review_decision(10, "maybe")
    assert get_review_decisions() == {10: "maybe"}

    set_review_decision(10, "accepted")
    assert get_review_decisions() == {10: "accepted"}


def test_invalid_review_decision_is_rejected(review_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.database.job_reviews.get_connection", lambda: _connect(review_db))

    with pytest.raises(ValueError):
        set_review_decision(10, "skip")
