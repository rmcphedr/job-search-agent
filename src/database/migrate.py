"""Lightweight SQLite schema migrations."""

from __future__ import annotations

import sqlite3

JOB_POSTINGS_COLUMNS: dict[str, str] = {
    "source_board": "TEXT",
    "discovery_run_id": "TEXT",
    "keyword_score": "REAL",
    "matched_keywords": "TEXT",
    "evaluated_at": "TEXT",
    "description_status": "TEXT",
    "description_source": "TEXT",
    "description_source_url": "TEXT",
    "description_checked_at": "TEXT",
    "description_error": "TEXT",
}

MIGRATION_VERSION = 11

JOB_EVALUATION_DDL = """
CREATE TABLE IF NOT EXISTS job_evaluation_queue (
    queue_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('queued','deferred','claimed','completed','failed','cancelled')),
    priority INTEGER NOT NULL DEFAULT 100,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    requested_model TEXT NOT NULL DEFAULT 'gpt-5.6-terra',
    requested_reasoning_effort TEXT NOT NULL DEFAULT 'low',
    defer_reason TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_error TEXT,
    eligible_at TEXT,
    claimed_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES job_postings(job_id)
);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_queue_status
    ON job_evaluation_queue(status, priority, eligible_at);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_queue_lease
    ON job_evaluation_queue(lease_expires_at);

CREATE TABLE IF NOT EXISTS job_evaluation_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('running','completed','budget_exhausted','failed','cancelled')),
    trigger TEXT NOT NULL DEFAULT 'manual',
    model TEXT NOT NULL DEFAULT 'gpt-5.6-terra',
    reasoning_effort TEXT NOT NULL DEFAULT 'low',
    max_jobs INTEGER,
    estimated_token_limit INTEGER,
    jobs_attempted INTEGER NOT NULL DEFAULT 0,
    jobs_completed INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER,
    output_tokens INTEGER,
    usage_provenance TEXT NOT NULL DEFAULT 'unavailable'
        CHECK (usage_provenance IN ('measured','estimated','unavailable','mixed')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_runs_started
    ON job_evaluation_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS job_evaluation_attempts (
    attempt_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    queue_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','completed','failed','escalated')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    duration_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    usage_provenance TEXT NOT NULL DEFAULT 'unavailable'
        CHECK (usage_provenance IN ('measured','estimated','unavailable')),
    escalation_reason TEXT,
    validation_outcome TEXT,
    error TEXT,
    FOREIGN KEY(run_id) REFERENCES job_evaluation_runs(run_id),
    FOREIGN KEY(queue_id) REFERENCES job_evaluation_queue(queue_id),
    FOREIGN KEY(job_id) REFERENCES job_postings(job_id)
);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_attempts_run
    ON job_evaluation_attempts(run_id, attempt_id);
CREATE INDEX IF NOT EXISTS idx_job_evaluation_attempts_job
    ON job_evaluation_attempts(job_id, attempt_id);
"""

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

JOB_REVIEWS_DDL = """
CREATE TABLE IF NOT EXISTS job_reviews (
    review_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('maybe', 'declined', 'accepted')),
    reviewed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);
CREATE INDEX IF NOT EXISTS idx_job_reviews_decision ON job_reviews (decision);
CREATE INDEX IF NOT EXISTS idx_job_reviews_job_id ON job_reviews (job_id);
"""

APPLICATION_PREPARATION_DDL = """
CREATE TABLE IF NOT EXISTS application_preparation_steps (
    step_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    step_key TEXT NOT NULL,
    title TEXT NOT NULL,
    position INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'complete', 'not_required')),
    details TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, step_key),
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);
CREATE INDEX IF NOT EXISTS idx_application_steps_job_id
    ON application_preparation_steps (job_id, position);
"""

EMPLOYER_ATS_SOURCES_DDL = """
CREATE TABLE IF NOT EXISTS employer_ats_sources (
    ats_source_id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('greenhouse', 'lever', 'ashby', 'workday')),
    board_url TEXT NOT NULL,
    board_token TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    discovery_method TEXT NOT NULL DEFAULT 'career_page',
    status TEXT NOT NULL DEFAULT 'not_run',
    last_checked_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, provider, board_url),
    FOREIGN KEY (company_id) REFERENCES companies (company_id)
);
CREATE INDEX IF NOT EXISTS idx_employer_ats_sources_company
    ON employer_ats_sources (company_id);
CREATE INDEX IF NOT EXISTS idx_employer_ats_sources_provider
    ON employer_ats_sources (provider, enabled);
"""

APPLICATION_WORKSPACE_DDL = """
CREATE TABLE IF NOT EXISTS application_sessions (
    session_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE,
    application_url TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'inspected',
    current_page TEXT,
    requires_account INTEGER NOT NULL DEFAULT 0,
    privacy_consent_required INTEGER NOT NULL DEFAULT 0,
    captcha_required INTEGER NOT NULL DEFAULT 0,
    automation_class TEXT NOT NULL DEFAULT 'assisted',
    classification_reason TEXT,
    last_inspected_at TEXT,
    last_error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);
CREATE TABLE IF NOT EXISTS application_fields (
    field_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    section TEXT NOT NULL,
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT 'text',
    required INTEGER NOT NULL DEFAULT 0,
    options_json TEXT,
    value TEXT,
    status TEXT NOT NULL DEFAULT 'missing',
    disposition TEXT NOT NULL DEFAULT 'pending',
    validation_error TEXT,
    last_observed_at TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, field_key),
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);
CREATE INDEX IF NOT EXISTS idx_application_fields_job
    ON application_fields (job_id, section, position);
"""

APPLICATION_AUTOMATION_DDL = """
CREATE TABLE IF NOT EXISTS application_facts (
    fact_key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'text',
    source TEXT NOT NULL DEFAULT 'user_confirmed',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS application_audit_events (
    event_id INTEGER PRIMARY KEY,
    job_id INTEGER,
    provider TEXT,
    event_type TEXT NOT NULL,
    target_key TEXT,
    outcome TEXT NOT NULL DEFAULT 'success',
    details_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);
CREATE INDEX IF NOT EXISTS idx_application_audit_job
    ON application_audit_events (job_id, created_at);
"""

APPLICATION_SUBMISSIONS_DDL = """
CREATE TABLE IF NOT EXISTS application_submissions (
    submission_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    provider TEXT,
    application_url TEXT,
    method TEXT NOT NULL DEFAULT 'user_confirmed_external',
    snapshot_json TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job_postings (job_id)
);
CREATE INDEX IF NOT EXISTS idx_application_submissions_job
    ON application_submissions (job_id, submitted_at DESC);
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
        version = 2

    if version < 3:
        if not _table_exists(connection, "job_reviews"):
            connection.executescript(JOB_REVIEWS_DDL)
            changes.append("job_reviews")

        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?);",
            (3,),
        )
        changes.append("schema_migrations.version=3")
        version = 3

    if version < 4:
        if not _table_exists(connection, "application_preparation_steps"):
            connection.executescript(APPLICATION_PREPARATION_DDL)
            changes.append("application_preparation_steps")

        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?);",
            (4,),
        )
        changes.append("schema_migrations.version=4")
        version = 4

    if version < 5:
        for column in (
            "description_status",
            "description_source",
            "description_source_url",
            "description_checked_at",
            "description_error",
        ):
            if not _column_exists(connection, "job_postings", column):
                connection.execute(f"ALTER TABLE job_postings ADD COLUMN {column} TEXT;")
                changes.append(f"job_postings.{column}")

        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?);",
            (5,),
        )
        changes.append("schema_migrations.version=5")
        version = 5

    if version < 6:
        if not _table_exists(connection, "employer_ats_sources"):
            connection.executescript(EMPLOYER_ATS_SOURCES_DDL)
            changes.append("employer_ats_sources")

        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?);",
            (6,),
        )
        changes.append("schema_migrations.version=6")
        version = 6

    if version < 7:
        connection.executescript(APPLICATION_WORKSPACE_DDL)
        changes.append("application_sessions, application_fields")
        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?);",
            (7,),
        )
        changes.append("schema_migrations.version=7")
        version = 7

    if version < 8:
        connection.executescript(APPLICATION_AUTOMATION_DDL)
        for column, column_type in (
            ("automation_class", "TEXT NOT NULL DEFAULT 'assisted'"),
            ("classification_reason", "TEXT"),
        ):
            if not _column_exists(connection, "application_sessions", column):
                connection.execute(f"ALTER TABLE application_sessions ADD COLUMN {column} {column_type};")
                changes.append(f"application_sessions.{column}")
        for column, column_type in (
            ("disposition", "TEXT NOT NULL DEFAULT 'pending'"),
            ("validation_error", "TEXT"),
            ("last_observed_at", "TEXT"),
        ):
            if not _column_exists(connection, "application_fields", column):
                connection.execute(f"ALTER TABLE application_fields ADD COLUMN {column} {column_type};")
                changes.append(f"application_fields.{column}")
        connection.execute("INSERT INTO schema_migrations (version) VALUES (?);", (8,))
        changes.extend(("application_facts", "application_audit_events", "schema_migrations.version=8"))
        version = 8

    if version < 9:
        connection.executescript(APPLICATION_SUBMISSIONS_DDL)
        connection.execute("INSERT INTO schema_migrations (version) VALUES (?);", (9,))
        changes.extend(("application_submissions", "schema_migrations.version=9"))
        version = 9

    if version < 10:
        if not _column_exists(connection, "job_postings", "fit_details"):
            connection.execute("ALTER TABLE job_postings ADD COLUMN fit_details TEXT;")
            changes.append("job_postings.fit_details")
        stale_columns = (
            "fit_score", "fit_reason", "evaluated_at", "description_status", "description_checked_at"
        )
        if all(_column_exists(connection, "job_postings", column) for column in stale_columns):
            connection.execute(
                """
                UPDATE job_postings
                SET fit_score = NULL, fit_reason = NULL, fit_details = NULL, evaluated_at = NULL
                WHERE description_status = 'enriched'
                  AND evaluated_at IS NOT NULL
                  AND datetime(description_checked_at) > datetime(evaluated_at);
                """
            )
        connection.execute("INSERT INTO schema_migrations (version) VALUES (?);", (10,))
        changes.append("schema_migrations.version=10")
        version = 10

    evaluation_tables_missing = any(
        not _table_exists(connection, table)
        for table in ("job_evaluation_queue", "job_evaluation_runs", "job_evaluation_attempts")
    )
    if version < 11 or evaluation_tables_missing:
        connection.executescript(JOB_EVALUATION_DDL)
        connection.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?);", (11,))
        changes.extend(
            (
                "job_evaluation_queue",
                "job_evaluation_runs",
                "job_evaluation_attempts",
                "schema_migrations.version=11",
            )
        )

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
