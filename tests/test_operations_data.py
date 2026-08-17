from pathlib import Path

import pytest

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.ui.operations_data import enroll_backlog, load_queue_metrics, preview_backlog


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
