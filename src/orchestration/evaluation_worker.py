"""Create budget-limited evaluation runs and claim compact agent packets."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.orchestration.evaluation_policy import EvaluationPolicy, estimate_tokens, load_evaluation_policy
from src.orchestration.job_evaluation_queue import claim_batch, claim_jobs


@dataclass(frozen=True)
class EvaluationJob:
    queue_id: int
    job_id: int
    title: str
    company_name: str
    location: str | None
    description: str
    description_checked_at: str
    estimated_tokens: int


@dataclass(frozen=True)
class EvaluationPacket:
    run_id: str
    model: str
    reasoning_effort: str
    profile_text: str
    jobs: list[EvaluationJob]
    estimated_input_tokens: int
    usage_provenance: str = "estimated"


def start_run(run_id: str, *, policy: EvaluationPolicy | None = None, trigger: str = "manual", connection=None) -> None:
    policy = policy or load_evaluation_policy()
    owned = connection is None
    conn = connection or get_connection()
    try:
        apply_migrations(conn)
        conn.execute(
            """INSERT INTO job_evaluation_runs
               (run_id,status,trigger,model,reasoning_effort,max_jobs,estimated_token_limit)
               VALUES (?,?,?,?,?,?,?)""",
            (run_id, "running", trigger, policy.default_model, policy.normal_reasoning_effort,
             policy.max_jobs_per_run, policy.estimated_token_limit),
        )
        if owned:
            conn.commit()
    finally:
        if owned:
            conn.close()


def claim_evaluation_packet(run_id: str, worker_id: str, *, policy: EvaluationPolicy | None = None,
                            profile_text: str = "", job_ids: list[int] | None = None,
                            discovery_run_id: str | None = None, connection=None) -> EvaluationPacket | None:
    policy = policy or load_evaluation_policy()
    filtered_claim = job_ids is not None or discovery_run_id is not None
    if filtered_claim and (not job_ids or not discovery_run_id):
        raise ValueError("job_ids and discovery_run_id are both required for filtered claims")
    owned = connection is None
    conn = connection or get_connection()
    conn.row_factory = sqlite3.Row
    try:
        apply_migrations(conn)
        run = conn.execute("SELECT * FROM job_evaluation_runs WHERE run_id=?", (run_id,)).fetchone()
        remaining_jobs = max(0, min(policy.batch_size, int(run["max_jobs"]) - int(run["jobs_attempted"])))
        used = int(run["input_tokens"] or 0) + int(run["output_tokens"] or 0)
        remaining_tokens = int(run["estimated_token_limit"]) - used
        profile_tokens = estimate_tokens(profile_text).tokens
        clauses = [
            "q.status='queued'",
            "j.active=1",
            "j.evaluated_at IS NULL",
            "j.description_status='enriched'",
            "j.description_checked_at IS NOT NULL",
        ]
        params: list[object] = []
        if filtered_claim:
            ordered_job_ids = list(dict.fromkeys(job_ids or []))
            placeholders = ",".join("?" for _ in ordered_job_ids)
            clauses.extend([f"j.job_id IN ({placeholders})", "j.discovery_run_id=?"])
            params.extend(ordered_job_ids)
            params.append(discovery_run_id)
        params.append(remaining_jobs)
        candidates = conn.execute(
            f"""SELECT q.queue_id,j.job_id,j.title,c.company_name,j.location,j.description,j.description_checked_at
                FROM job_evaluation_queue q JOIN job_postings j USING(job_id)
                JOIN companies c USING(company_id)
                WHERE {' AND '.join(clauses)}
                ORDER BY q.priority,q.eligible_at,q.queue_id LIMIT ?""",
            params,
        ).fetchall()
        if filtered_claim:
            requested_order = {job_id: index for index, job_id in enumerate(ordered_job_ids)}
            candidates = sorted(candidates, key=lambda row: requested_order[int(row["job_id"])])
        selected = []
        projected = profile_tokens
        for row in candidates:
            tokens = estimate_tokens(str(row["description"] or "")).tokens
            if projected + tokens > remaining_tokens:
                break
            selected.append((row, tokens))
            projected += tokens
        if not selected:
            conn.execute("UPDATE job_evaluation_runs SET status='budget_exhausted',completed_at=CURRENT_TIMESTAMP WHERE run_id=?", (run_id,))
            if owned:
                conn.commit()
            return None
        if filtered_claim:
            claimed = claim_jobs(
                job_ids=[int(row["job_id"]) for row, _ in selected],
                worker_id=worker_id,
                lease_seconds=policy.lease_seconds,
                connection=conn,
            )
        else:
            claimed = claim_batch(run_id=run_id, worker_id=worker_id, limit=len(selected), lease_seconds=policy.lease_seconds, connection=conn)
        by_id = {item.job_id: item for item in claimed}
        jobs = [EvaluationJob(queue_id=by_id[int(row["job_id"])].queue_id, job_id=int(row["job_id"]),
                              title=row["title"], company_name=row["company_name"], location=row["location"],
                              description=row["description"], description_checked_at=row["description_checked_at"],
                              estimated_tokens=tokens) for row, tokens in selected if int(row["job_id"]) in by_id]
        conn.execute("UPDATE job_evaluation_runs SET jobs_attempted=jobs_attempted+?,input_tokens=coalesce(input_tokens,0)+?,usage_provenance='estimated' WHERE run_id=?",
                     (len(jobs), projected, run_id))
        if owned:
            conn.commit()
        return EvaluationPacket(run_id, policy.default_model, policy.normal_reasoning_effort, profile_text, jobs, projected)
    finally:
        if owned:
            conn.close()
