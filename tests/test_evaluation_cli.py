from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.orchestration.evaluation_cli import main, parser
from src.orchestration.job_evaluation_queue import enqueue_job


def test_daily_claim_defaults_to_luna_with_bounded_budget() -> None:
    args = parser().parse_args(
        [
            "daily-claim",
            "--run-id", "eval-1",
            "--discovery-run-id", "scan-1",
            "--job-ids", "1,2,3",
            "--worker-id", "codex-scheduled",
        ]
    )

    assert (args.model, args.reasoning, args.max_jobs, args.token_limit) == (
        "gpt-5.6-luna", "low", 5, 30_000
    )


def test_daily_claim_rejects_more_than_five_jobs() -> None:
    with pytest.raises(ValueError, match="between 1 and 5"):
        main(
            [
                "daily-claim",
                "--run-id", "eval-1",
                "--discovery-run-id", "scan-1",
                "--job-ids", "1,2,3,4,5,6",
                "--worker-id", "codex-scheduled",
            ]
        )


def test_daily_claim_returns_only_ready_jobs_from_requested_scan(
    tmp_path, monkeypatch, capsys
) -> None:
    connection = get_connection(tmp_path / "jobs.db")
    connection.executescript(Path("src/database/schema.sql").read_text())
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO companies (company_id,company_name,website) VALUES (1,'Acme','https://acme.test')"
    )
    for job_id, scan_id in ((1, "scan-1"), (2, "old-scan")):
        connection.execute(
            """INSERT INTO job_postings
               (job_id,company_id,title,description,active,description_status,
                description_checked_at,discovery_run_id)
               VALUES (?,1,?,'verified role',1,'enriched',CURRENT_TIMESTAMP,?)""",
            (job_id, f"Role {job_id}", scan_id),
        )
        enqueue_job(job_id, description_ready=True, connection=connection)
    connection.commit()
    connection.close()
    monkeypatch.setattr(
        "src.orchestration.evaluation_worker.get_connection",
        lambda: get_connection(tmp_path / "jobs.db"),
    )

    assert main(
        [
            "daily-claim",
            "--run-id", "eval-1",
            "--discovery-run-id", "scan-1",
            "--job-ids", "1,1,2",
            "--worker-id", "codex-scheduled",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["model"] == "gpt-5.6-luna"
    assert [job["job_id"] for job in payload["jobs"]] == [1]
    connection = get_connection(tmp_path / "jobs.db")
    run = connection.execute(
        "SELECT trigger,max_jobs,estimated_token_limit FROM job_evaluation_runs WHERE run_id='eval-1'"
    ).fetchone()
    assert tuple(run) == ("scheduled_daily", 5, 30_000)
