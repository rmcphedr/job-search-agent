"""Synchronous validated commit boundary for agent job-fit results."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.llm.schemas import JobFitResult


@dataclass(frozen=True)
class SubmissionResult:
    completed: int
    needs_escalation: list[int]


def reconcile_run_completion(run_id: str, *, connection=None) -> bool:
    """Mark a run complete when all claimed work was submitted."""
    owned = connection is None
    conn = connection or get_connection()
    try:
        cursor = conn.execute(
            """UPDATE job_evaluation_runs SET status='completed', completed_at=CURRENT_TIMESTAMP
               WHERE run_id=? AND status='running' AND jobs_attempted > 0
                 AND jobs_completed >= jobs_attempted""",
            (run_id,),
        )
        if owned:
            conn.commit()
        return cursor.rowcount == 1
    finally:
        if owned:
            conn.close()


def submit_job_evaluations(run_id: str, queue_ids: list[int], payload: list[dict], *, model: str,
                           reasoning_effort: str, input_tokens: int | None = None,
                           output_tokens: int | None = None, usage_provenance: str = "unavailable",
                           confidence_threshold: float = 6.0, connection=None) -> SubmissionResult:
    records = [JobFitResult.model_validate(item) for item in payload]
    if len(records) != len(queue_ids):
        raise ValueError("queue_ids and payload must have equal length")
    owned = connection is None
    conn = connection or get_connection()
    conn.row_factory = sqlite3.Row
    try:
        apply_migrations(conn)
        validated = []
        escalations = []
        for queue_id, record in zip(queue_ids, records):
            row = conn.execute(
                """SELECT q.job_id,q.status,j.title,c.company_name,j.active,j.description_status,j.description_checked_at
                   FROM job_evaluation_queue q JOIN job_postings j USING(job_id)
                   JOIN companies c USING(company_id) WHERE q.queue_id=?""", (queue_id,)
            ).fetchone()
            if not row or row["status"] != "claimed" or record.job_id != row["job_id"]:
                raise ValueError(f"queue identity mismatch: {queue_id}")
            if record.job_title.strip() != row["title"].strip() or record.company_name.strip() != row["company_name"].strip():
                raise ValueError(f"job identity mismatch: {record.job_id}")
            if not row["active"] or row["description_status"] != "enriched" or not row["description_checked_at"]:
                raise ValueError(f"job is not evaluation-ready: {record.job_id}")
            if record.confidence < confidence_threshold and reasoning_effort != "medium":
                escalations.append(queue_id)
                continue
            validated.append((queue_id, record))
        for queue_id, record in validated:
            conn.execute("UPDATE job_postings SET fit_score=?,fit_reason=?,fit_details=?,evaluated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                         (record.fit_score, record.why_fit, record.model_dump_json(), record.job_id))
            conn.execute("UPDATE job_evaluation_queue SET status='completed',completed_at=CURRENT_TIMESTAMP,lease_owner=NULL,lease_expires_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE queue_id=?", (queue_id,))
            conn.execute("""INSERT INTO job_evaluation_attempts
                (run_id,queue_id,job_id,model,reasoning_effort,status,completed_at,input_tokens,output_tokens,usage_provenance,validation_outcome)
                VALUES (?,?,?,?,?,'completed',CURRENT_TIMESTAMP,?,?,?,'valid')""",
                (run_id, queue_id, record.job_id, model, reasoning_effort, input_tokens, output_tokens, usage_provenance))
        conn.execute(
            """UPDATE job_evaluation_runs
               SET jobs_completed=jobs_completed+?, output_tokens=coalesce(output_tokens,0)+?,
                   status=CASE WHEN jobs_completed+? >= jobs_attempted AND ?=0 THEN 'completed' ELSE status END,
                   completed_at=CASE WHEN jobs_completed+? >= jobs_attempted AND ?=0 THEN CURRENT_TIMESTAMP ELSE completed_at END
               WHERE run_id=?""",
            (len(validated), output_tokens or 0, len(validated), len(escalations), len(validated), len(escalations), run_id),
        )
        if owned:
            conn.commit()
        return SubmissionResult(len(validated), escalations)
    except Exception:
        if owned:
            conn.rollback()
        raise
    finally:
        if owned:
            conn.close()
