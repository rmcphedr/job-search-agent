from __future__ import annotations

from pathlib import Path

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.orchestration.evaluation_policy import EvaluationPolicy, estimate_tokens, load_evaluation_policy
from src.orchestration.evaluation_worker import claim_evaluation_packet, start_run
from src.orchestration.job_evaluation_queue import enqueue_job
from src.orchestration.evaluation_submission import submit_job_evaluations


def test_policy_defaults_and_token_estimate() -> None:
    policy = load_evaluation_policy(Path("config/agent_evaluation.yaml"))
    assert policy.default_model == "gpt-5.6-terra"
    assert policy.normal_reasoning_effort == "low"
    assert policy.batch_size == 5
    assert estimate_tokens("x" * 400).tokens == 100
    assert estimate_tokens("x" * 400).provenance == "estimated"


def test_worker_claims_only_jobs_that_fit_budget(tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    connection = get_connection(db_path)
    connection.executescript(Path("src/database/schema.sql").read_text())
    apply_migrations(connection)
    connection.execute("INSERT INTO companies VALUES (1,'Acme','https://acme.test',NULL,NULL,NULL,NULL,NULL,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
    for job_id in (1, 2):
        connection.execute(
            """INSERT INTO job_postings
               (job_id,company_id,title,description,active,description_status,description_checked_at)
               VALUES (?,1,?, ?,1,'enriched',CURRENT_TIMESTAMP)""",
            (job_id, f"Role {job_id}", "a" * 400),
        )
        enqueue_job(job_id, description_ready=True, connection=connection)
    policy = EvaluationPolicy(batch_size=5, max_jobs_per_run=1, estimated_token_limit=10000)
    start_run("run-1", policy=policy, connection=connection)

    packet = claim_evaluation_packet("run-1", "worker", policy=policy, profile_text="profile", connection=connection)

    assert packet is not None
    assert len(packet.jobs) == 1
    assert packet.profile_text == "profile"
    assert connection.execute("SELECT count(*) FROM job_evaluation_queue WHERE status='queued'").fetchone()[0] == 1


def test_worker_claims_only_selected_jobs_from_current_discovery_run(tmp_path) -> None:
    connection = get_connection(tmp_path / "jobs.db")
    connection.executescript(Path("src/database/schema.sql").read_text())
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO companies (company_id,company_name,website) VALUES (1,'Acme','https://acme.test')"
    )
    for job_id, discovery_run_id in ((1, "daily-1"), (2, "daily-1"), (3, "old-run")):
        connection.execute(
            """INSERT INTO job_postings
               (job_id,company_id,title,description,active,description_status,
                description_checked_at,discovery_run_id)
               VALUES (?,1,?,'verified',1,'enriched',CURRENT_TIMESTAMP,?)""",
            (job_id, f"Role {job_id}", discovery_run_id),
        )
        enqueue_job(job_id, description_ready=True, connection=connection)
    policy = EvaluationPolicy(
        default_model="gpt-5.6-luna",
        batch_size=5,
        max_jobs_per_run=5,
        estimated_token_limit=30_000,
    )
    start_run("daily-eval-1", policy=policy, trigger="scheduled_daily", connection=connection)

    packet = claim_evaluation_packet(
        "daily-eval-1",
        "codex-scheduled",
        policy=policy,
        job_ids=[2, 3],
        discovery_run_id="daily-1",
        connection=connection,
    )

    assert packet is not None
    assert [job.job_id for job in packet.jobs] == [2]
    states = dict(connection.execute("SELECT job_id,status FROM job_evaluation_queue"))
    assert states == {1: "queued", 2: "claimed", 3: "queued"}


def test_filtered_worker_requires_ids_and_discovery_run_together(tmp_path) -> None:
    connection = get_connection(tmp_path / "jobs.db")
    connection.executescript(Path("src/database/schema.sql").read_text())
    apply_migrations(connection)
    policy = EvaluationPolicy()
    start_run("daily-eval-1", policy=policy, connection=connection)

    import pytest

    with pytest.raises(ValueError, match="job_ids and discovery_run_id"):
        claim_evaluation_packet(
            "daily-eval-1", "codex-scheduled", policy=policy,
            job_ids=[1], connection=connection,
        )


def test_submission_atomically_completes_claimed_job(tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    connection = get_connection(db_path)
    connection.executescript(Path("src/database/schema.sql").read_text())
    apply_migrations(connection)
    connection.execute("INSERT INTO companies (company_id,company_name,website) VALUES (1,'Acme','https://acme.test')")
    connection.execute("""INSERT INTO job_postings (job_id,company_id,title,description,active,description_status,description_checked_at)
                          VALUES (1,1,'ML Scientist','full',1,'enriched',CURRENT_TIMESTAMP)""")
    item = enqueue_job(1, description_ready=True, connection=connection)
    policy = EvaluationPolicy(max_jobs_per_run=1)
    start_run("run-1", policy=policy, connection=connection)
    claim_evaluation_packet("run-1", "worker", policy=policy, connection=connection)
    result = submit_job_evaluations("run-1", [item.queue_id], [{"job_id":1,"job_title":"ML Scientist","company_name":"Acme","fit_score":8,"why_fit":"Strong","confidence":8}], model="gpt-5.6-terra", reasoning_effort="low", connection=connection)
    assert result.completed == 1
    assert connection.execute("SELECT fit_score FROM job_postings WHERE job_id=1").fetchone()[0] == 8
    assert connection.execute("SELECT status FROM job_evaluation_queue WHERE job_id=1").fetchone()[0] == "completed"
    assert connection.execute("SELECT status FROM job_evaluation_runs WHERE run_id='run-1'").fetchone()[0] == "completed"
