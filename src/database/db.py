"""SQLite database utilities for job-search-agent."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DATABASE_PATH = Path("data/job_search.db")
SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"

KNOWN_TABLES = (
    "companies",
    "company_pages",
    "company_profiles",
    "job_postings",
    "tracked_jobs",
    "runs",
)


def get_project_root() -> Path:
    """Return the project root directory containing config/settings.yaml."""
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / "config" / "settings.yaml").exists():
            return candidate
    return current.parent.parent


def load_settings() -> dict[str, Any]:
    """Load project settings from config/settings.yaml."""
    settings_path = get_project_root() / "config" / "settings.yaml"
    if not settings_path.exists():
        return {}

    try:
        with settings_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Failed to load settings from {settings_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Settings file {settings_path} must contain a YAML mapping.")

    return data


def get_database_path() -> Path:
    """Resolve the SQLite database path from settings, with a safe fallback."""
    try:
        settings = load_settings()
        paths = settings.get("paths", {})
        if isinstance(paths, dict):
            database_path = paths.get("database")
            if isinstance(database_path, str) and database_path.strip():
                return get_project_root() / database_path
    except RuntimeError:
        pass

    return get_project_root() / DEFAULT_DATABASE_PATH


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with row factory enabled."""
    path = db_path or get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        connection = sqlite3.connect(path)
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to connect to database at {path}: {exc}") from exc

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def execute_sql_file(sql_file_path: Path, db_path: Path | None = None) -> None:
    """Execute a SQL file against the configured database."""
    if not sql_file_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_file_path}")

    try:
        sql = sql_file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to read SQL file {sql_file_path}: {exc}") from exc

    connection = get_connection(db_path)
    try:
        connection.executescript(sql)
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise RuntimeError(f"Failed to execute SQL file {sql_file_path}: {exc}") from exc
    finally:
        connection.close()


def table_exists(table_name: str, db_path: Path | None = None) -> bool:
    """Return True if the given table exists in the database."""
    connection = get_connection(db_path)
    try:
        cursor = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1;",
            (table_name,),
        )
        return cursor.fetchone() is not None
    finally:
        connection.close()


def get_table_counts(db_path: Path | None = None) -> dict[str, int]:
    """Return row counts for all known application tables."""
    connection = get_connection(db_path)
    counts: dict[str, int] = {}

    try:
        for table_name in KNOWN_TABLES:
            if table_exists(table_name, db_path):
                cursor = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name};")
                counts[table_name] = int(cursor.fetchone()["count"])
            else:
                counts[table_name] = 0
    finally:
        connection.close()

    return counts
