"""Tests for the application-preparation workflow."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.application_preparation import (
    list_application_steps,
    preparation_is_complete,
    start_application_preparation,
    update_application_step,
)


@pytest.fixture()
def preparation_db(tmp_path: Path) -> Path:
    path = tmp_path / "preparation.db"
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE job_postings (
            job_id INTEGER PRIMARY KEY,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL
        );
        CREATE TABLE tracked_jobs (
            tracked_id INTEGER PRIMARY KEY,
            job_id INTEGER NOT NULL UNIQUE,
            stage TEXT NOT NULL DEFAULT 'tracked',
            updated_at TEXT,
            FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
        );
        INSERT INTO job_postings VALUES (10, 1, 'ML Scientist');
        INSERT INTO tracked_jobs (job_id, stage) VALUES (10, 'tracked');
        """
    )
    connection.commit()
    connection.close()
    return path


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def test_start_creates_ordered_steps_and_moves_stage(
    preparation_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.database.application_preparation.get_connection", lambda: _connect(preparation_db)
    )
    steps = start_application_preparation(10)
    assert len(steps) == 6
    assert steps[0]["step_key"] == "requirements"

    connection = _connect(preparation_db)
    try:
        stage = connection.execute("SELECT stage FROM tracked_jobs WHERE job_id = 10;").fetchone()
        assert stage["stage"] == "applying"
    finally:
        connection.close()


def test_steps_are_idempotent_and_completion_is_calculated(
    preparation_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.database.application_preparation.get_connection", lambda: _connect(preparation_db)
    )
    start_application_preparation(10)
    assert len(start_application_preparation(10)) == 6

    for step in list_application_steps(10):
        update_application_step(
            10,
            step["step_key"],
            status="complete",
            details="Reviewed output",
        )
    assert preparation_is_complete(list_application_steps(10)) is True
