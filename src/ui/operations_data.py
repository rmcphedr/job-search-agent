"""Read-only operations aggregates and guarded backlog enrollment."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.orchestration.evaluation_policy import estimate_tokens
from src.orchestration.job_evaluation_queue import enqueue_job


@dataclass(frozen=True)
class QueueMetrics:
    ready: int = 0
    deferred: int = 0
    claimed: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    stale: int = 0


@dataclass(frozen=True)
class BacklogRow:
    job_id: int
    company_name: str
    title: str
    date_found: str | None
    keyword_score: float | None
    source_board: str | None
    estimated_tokens: int


def load_queue_metrics(*, connection=None) -> QueueMetrics:
    owned = connection is None
    conn = connection or get_connection()
    try:
        apply_migrations(conn)
        if owned:
            conn.commit()
        counts = {row[0]: row[1] for row in conn.execute("SELECT status,count(*) FROM job_evaluation_queue GROUP BY status")}
        stale = conn.execute("SELECT count(*) FROM job_evaluation_queue WHERE status='claimed' AND datetime(lease_expires_at)<=datetime('now')").fetchone()[0]
        return QueueMetrics(ready=counts.get("queued",0), deferred=counts.get("deferred",0), claimed=counts.get("claimed",0),
                            completed=counts.get("completed",0), failed=counts.get("failed",0), cancelled=counts.get("cancelled",0), stale=stale)
    finally:
        if owned: conn.close()


def preview_backlog(*, limit: int, verified_only: bool = True, source: str | None = None,
                    company: str | None = None, min_keyword_score: float = 0.0, connection=None) -> list[BacklogRow]:
    owned = connection is None
    conn = connection or get_connection()
    try:
        apply_migrations(conn)
        if owned:
            conn.commit()
        clauses = ["j.active=1", "j.evaluated_at IS NULL", "q.queue_id IS NULL", "coalesce(j.keyword_score,0)>=?"]
        params: list[object] = [min_keyword_score]
        if verified_only: clauses.append("j.description_status='enriched' AND j.description_checked_at IS NOT NULL")
        if source: clauses.append("j.source_board=?"); params.append(source)
        if company: clauses.append("c.company_name=?"); params.append(company)
        params.append(limit)
        rows = conn.execute(f"""SELECT j.job_id,c.company_name,j.title,j.date_found,j.keyword_score,j.source_board,j.description
            FROM job_postings j JOIN companies c USING(company_id) LEFT JOIN job_evaluation_queue q USING(job_id)
            WHERE {' AND '.join(clauses)} ORDER BY datetime(j.date_found) DESC,j.job_id DESC LIMIT ?""", params).fetchall()
        return [BacklogRow(int(r[0]),r[1],r[2],r[3],r[4],r[5],estimate_tokens(str(r[6] or '')).tokens) for r in rows]
    finally:
        if owned: conn.close()


def enroll_backlog(job_ids: list[int], *, confirm: bool, max_jobs: int, token_limit: int, connection=None) -> int:
    if not confirm: raise ValueError("explicit confirmation is required")
    if not job_ids or len(job_ids) > max_jobs: raise ValueError("bounded job selection is required")
    owned = connection is None
    conn = connection or get_connection()
    try:
        placeholders = ",".join("?" for _ in job_ids)
        rows = conn.execute(f"SELECT job_id,description,description_status,description_checked_at FROM job_postings WHERE active=1 AND evaluated_at IS NULL AND job_id IN ({placeholders})", job_ids).fetchall()
        projected = sum(estimate_tokens(str(r[1] or '')).tokens for r in rows)
        if projected > token_limit: raise ValueError("selection exceeds estimated token ceiling")
        for row in rows:
            enqueue_job(int(row[0]), description_ready=row[2]=="enriched" and bool(row[3]), connection=conn)
        if owned: conn.commit()
        return len(rows)
    finally:
        if owned: conn.close()


def load_recent_evaluation_runs(*, connection=None) -> pd.DataFrame:
    owned = connection is None; conn = connection or get_connection()
    try: return pd.read_sql_query("SELECT * FROM job_evaluation_runs ORDER BY started_at DESC LIMIT 50", conn)
    finally:
        if owned: conn.close()


def load_model_efficiency(*, connection=None) -> pd.DataFrame:
    owned = connection is None; conn = connection or get_connection()
    try:
        frame = pd.read_sql_query("""SELECT model,reasoning_effort,count(*) attempts,
            sum(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,
            avg(duration_ms) avg_duration_ms,sum(input_tokens) input_tokens,sum(output_tokens) output_tokens,
            CASE WHEN min(usage_provenance)=max(usage_provenance)
                 THEN min(usage_provenance) ELSE 'mixed' END usage_provenance
            FROM job_evaluation_attempts GROUP BY model,reasoning_effort""", conn)
        for column in ("avg_duration_ms", "input_tokens", "output_tokens"):
            frame[column] = frame[column].astype(object).where(frame[column].notna(), "Unavailable")
        return frame
    finally:
        if owned: conn.close()
