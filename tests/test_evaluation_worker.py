from __future__ import annotations

from pathlib import Path

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.orchestration.evaluation_policy import EvaluationPolicy, estimate_tokens, load_evaluation_policy
from src.orchestration.evaluation_worker import claim_evaluation_packet, start_run
from src.orchestration.job_evaluation_queue import enqueue_job


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
