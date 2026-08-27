from pathlib import Path

import pytest

from src.database.db import get_connection
from src.database.migrate import MIGRATION_VERSION, apply_migrations
from src.ui.operations_data import (
    enroll_backlog,
    load_model_efficiency,
    load_queue_metrics,
    preview_backlog,
)


def test_backlog_preview_is_read_only_and_enrollment_requires_confirmation(tmp_path):
    connection = get_connection(tmp_path / "jobs.db")
    connection.executescript(Path("src/database/schema.sql").read_text())
    apply_migrations(connection)
    connection.execute("INSERT INTO companies (company_id,company_name,website) VALUES (1,'Acme','https://acme.test')")
    connection.execute("""INSERT INTO job_postings (job_id,company_id,title,description,active,keyword_score,description_status,description_checked_at,date_found)
                          VALUES (1,1,'New Role','full',1,.8,'enriched',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
    rows = preview_backlog(limit=10, verified_only=True, connection=connection)
    assert [row.job_id for row in rows] == [1]
    assert load_queue_metrics(connection=connection).ready == 0
    with pytest.raises(ValueError):
        enroll_backlog([1], confirm=False, max_jobs=10, token_limit=50000, connection=connection)
    assert enroll_backlog([1], confirm=True, max_jobs=10, token_limit=50000, connection=connection) == 1


def test_owned_metrics_connection_persists_pending_migration(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    connection = get_connection(db_path)
    connection.executescript(Path("src/database/schema.sql").read_text())
    connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    connection.execute("INSERT INTO schema_migrations(version) VALUES (10)")
    connection.execute("DROP TABLE job_evaluation_attempts")
    connection.execute("DROP TABLE job_evaluation_runs")
    connection.execute("DROP TABLE job_evaluation_queue")
    connection.commit()
    connection.close()
    monkeypatch.setattr("src.ui.operations_data.get_connection", lambda: get_connection(db_path))

    load_queue_metrics()

    reopened = get_connection(db_path)
    assert reopened.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == MIGRATION_VERSION
    assert reopened.execute("SELECT count(*) FROM job_evaluation_queue").fetchone()[0] == 0


def test_model_efficiency_labels_unavailable_telemetry(tmp_path):
    connection = get_connection(tmp_path / "jobs.db")
    connection.executescript(Path("src/database/schema.sql").read_text())
    apply_migrations(connection)
    connection.execute("INSERT INTO companies (company_id,company_name,website) VALUES (1,'Acme','https://acme.test')")
    connection.execute("INSERT INTO job_postings (job_id,company_id,title) VALUES (1,1,'Role')")
    connection.execute("INSERT INTO job_evaluation_queue (queue_id,job_id,status) VALUES (1,1,'completed')")
    connection.execute("INSERT INTO job_evaluation_runs (run_id,status) VALUES ('run-1','completed')")
    connection.execute(
        """INSERT INTO job_evaluation_attempts
           (run_id,queue_id,job_id,model,reasoning_effort,status,usage_provenance)
           VALUES ('run-1',1,1,'codex-current-session','low','completed','unavailable')"""
    )

    row = load_model_efficiency(connection=connection).iloc[0]

    assert row["avg_duration_ms"] == "Unavailable"
    assert row["input_tokens"] == "Unavailable"
    assert row["output_tokens"] == "Unavailable"
    assert row["usage_provenance"] == "unavailable"


def test_model_efficiency_keeps_estimated_token_totals_numeric(tmp_path):
    connection = get_connection(tmp_path / "jobs.db")
    connection.executescript(Path("src/database/schema.sql").read_text())
    apply_migrations(connection)
    connection.execute("INSERT INTO companies (company_id,company_name,website) VALUES (1,'Acme','https://acme.test')")
    connection.execute("INSERT INTO job_postings (job_id,company_id,title) VALUES (1,1,'Role')")
    connection.execute("INSERT INTO job_evaluation_queue (queue_id,job_id,status) VALUES (1,1,'completed')")
    connection.execute("INSERT INTO job_evaluation_runs (run_id,status) VALUES ('run-1','completed')")
    connection.execute(
        """INSERT INTO job_evaluation_attempts
           (run_id,queue_id,job_id,model,reasoning_effort,status,input_tokens,
            output_tokens,usage_provenance)
           VALUES ('run-1',1,1,'gpt-5.6-luna','low','completed',120,30,'estimated')"""
    )

    row = load_model_efficiency(connection=connection).iloc[0]

    assert row["input_tokens"] == 120
    assert row["output_tokens"] == 30
    assert row["usage_provenance"] == "estimated"
