from __future__ import annotations

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.jobs.job_models import JobCandidate
from src.jobs.save_jobs import SaveJobsOptions, save_jobs


def test_new_jobs_are_queued_only_when_description_is_verified(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "jobs.db"
    connection = get_connection(db_path)
    connection.executescript(open("src/database/schema.sql", encoding="utf-8").read())
    apply_migrations(connection)
    connection.execute("INSERT INTO companies (company_id,company_name,website) VALUES (1,'Acme','https://acme.test')")
    connection.commit()
    connection.close()
    monkeypatch.setattr("src.jobs.save_jobs.get_connection", lambda: get_connection(db_path))

    save_jobs([
        JobCandidate(company_name="Acme", title="Verified", url="https://acme.test/1", description="Full role text", source_career_page="https://acme.test/careers"),
        JobCandidate(company_name="Acme", title="Missing", url="https://acme.test/2", source_career_page="https://acme.test/careers"),
    ], pending_evaluation=True)

    connection = get_connection(db_path)
    states = dict(connection.execute("SELECT j.title,q.status FROM job_postings j JOIN job_evaluation_queue q USING(job_id)"))
    assert states == {"Verified": "queued", "Missing": "deferred"}


def test_description_enrichment_tracks_current_discovery_run(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "jobs.db"
    connection = get_connection(db_path)
    connection.executescript(open("src/database/schema.sql", encoding="utf-8").read())
    apply_migrations(connection)
    connection.execute("INSERT INTO companies (company_id,company_name,website) VALUES (1,'Acme','https://acme.test')")
    connection.execute(
        """INSERT INTO job_postings
           (job_id,company_id,title,url,active,discovery_run_id)
           VALUES (1,1,'Rediscovered','https://acme.test/rediscovered',1,'old-run')"""
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr("src.jobs.save_jobs.get_connection", lambda: get_connection(db_path))

    save_jobs(
        [
            JobCandidate(
                company_name="Acme",
                title="Rediscovered",
                url="https://acme.test/rediscovered",
                description="Verified role description",
                source_career_page="https://acme.test/careers",
            )
        ],
        options=SaveJobsOptions(pending_evaluation=True, discovery_run_id="daily-1"),
    )

    connection = get_connection(db_path)
    row = connection.execute(
        "SELECT discovery_run_id,description_status FROM job_postings WHERE job_id=1"
    ).fetchone()
    assert tuple(row) == ("daily-1", "enriched")
    assert connection.execute(
        "SELECT status FROM job_evaluation_queue WHERE job_id=1"
    ).fetchone()[0] == "queued"
