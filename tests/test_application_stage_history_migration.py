"""Tests for application stage-history migration and backfill."""

import sqlite3

from src.database.migrate import apply_migrations


def test_migration_backfills_known_application_stages() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO schema_migrations(version) VALUES (11);
        CREATE TABLE tracked_jobs (
            tracked_id INTEGER PRIMARY KEY,
            job_id INTEGER NOT NULL UNIQUE,
            stage TEXT NOT NULL,
            notes TEXT,
            applied_at TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        INSERT INTO tracked_jobs(job_id, stage, applied_at, updated_at)
        VALUES (7, 'rejected', '2026-08-01T12:00:00Z', '2026-08-20T12:00:00Z');
        """
    )

    changes = apply_migrations(connection)

    assert "application_stage_history" in changes
    rows = connection.execute(
        "SELECT stage FROM application_stage_history WHERE job_id = 7 ORDER BY entered_at, history_id"
    ).fetchall()
    assert [row[0] for row in rows] == ["applied", "rejected"]
