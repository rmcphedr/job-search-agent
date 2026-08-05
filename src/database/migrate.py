"""Lightweight SQLite schema migrations."""

from __future__ import annotations

import sqlite3

JOB_POSTINGS_COLUMNS: dict[str, str] = {
    "source_board": "TEXT",
    "discovery_run_id": "TEXT",
    "keyword_score": "REAL",
    "matched_keywords": "TEXT",
    "evaluated_at": "TEXT",
}

MIGRATION_VERSION = 2

TRACKED_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS tracked_jobs (
    tracked_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE,
    stage TEXT NOT NULL DEFAULT 'tracked',
    notes TEXT,
    applied_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);
CREATE INDEX IF NOT EXISTS idx_tracked_jobs_stage ON tracked_jobs (stage);
CREATE INDEX IF NOT EXISTS idx_tracked_jobs_job_id ON tracked_jobs (job_id);
"""


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table});").fetchall()
    return any(row["name"] == column for row in rows)


def _ensure_schema_migrations_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def _current_migration_version(connection: sqlite3.Connection) -> int:
    _ensure_schema_migrations_table(connection)
    row = connection.execute(
        "SELECT MAX(version) AS version FROM schema_migrations;"
    ).fetchone()
    if row is None or row["version"] is None:
        return 0
    return int(row["version"])


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1;",
        (table,),
    ).fetchone()
    return row is not None


def apply_migrations(connection: sqlite3.Connection) -> list[str]:
    """Apply pending migrations. Returns human-readable change log."""
    changes: list[str] = []
    version = _current_migration_version(connection)

    if version < 1:
        for column, column_type in JOB_POSTINGS_COLUMNS.items():
            if not _column_exists(connection, "job_postings", column):
                connection.execute(
                    f"ALTER TABLE job_postings ADD COLUMN {column} {column_type};"
                )
                changes.append(f"job_postings.{column}")

        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?);",
            (1,),
        )
        changes.append("schema_migrations.version=1")
        version = 1

    if version < 2:
        if not _table_exists(connection, "tracked_jobs"):
            connection.executescript(TRACKED_JOBS_DDL)
            changes.append("tracked_jobs")

        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?);",
            (2,),
        )
        changes.append("schema_migrations.version=2")

    return changes


def ensure_migrations(db_path=None) -> list[str]:
    """Open connection, apply migrations, commit, and return changes."""
    from src.database.db import get_connection

    connection = get_connection(db_path)
    try:
        changes = apply_migrations(connection)
        if changes:
            connection.commit()
        return changes
    finally:
        connection.close()
