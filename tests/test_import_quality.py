"""Bad live imports are quarantined without touching older jobs."""

from pathlib import Path

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.jobs.import_quality import quarantine_import
from src.orchestration.job_evaluation_queue import enqueue_job


def test_quarantine_is_scoped_to_one_run(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "jobs.db"
    conn = get_connection(db_path)
    conn.executescript(Path("src/database/schema.sql").read_text())
    apply_migrations(conn)
    conn.execute("INSERT INTO companies (company_id,company_name,website) VALUES (1,'Arbor','https://arbor.test')")
    for job_id, run_id in ((1, "scan-new"), (2, "scan-old")):
        conn.execute(
            "INSERT INTO job_postings (job_id,company_id,title,active,discovery_run_id) VALUES (?,1,?,1,?)",
            (job_id, f"Role {job_id}", run_id),
        )
        enqueue_job(job_id, description_ready=True, connection=conn)
    conn.execute(
        "INSERT INTO employer_ats_sources (ats_source_id,company_id,provider,board_url) VALUES (5,1,'lever','https://jobs.lever.co/shared')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("src.jobs.import_quality.get_connection", lambda: get_connection(db_path))

    result = quarantine_import(
        run_id="scan-new", job_ids=[1], ats_source_ids=[5], reason="wrong employer"
    )

    conn = get_connection(db_path)
    assert result["job_ids"] == [1]
    assert conn.execute("SELECT active FROM job_postings WHERE job_id=1").fetchone()[0] == 0
    assert conn.execute("SELECT active FROM job_postings WHERE job_id=2").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM job_evaluation_queue WHERE job_id=1").fetchone()[0] == "cancelled"
    assert conn.execute("SELECT enabled FROM employer_ats_sources WHERE ats_source_id=5").fetchone()[0] == 0
    conn.close()
