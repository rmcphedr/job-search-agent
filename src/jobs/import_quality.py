"""Review a specific discovery run and quarantine confirmed bad imports."""

from __future__ import annotations

import json
from typing import Iterable

from src.database.db import get_connection
from src.database.migrate import apply_migrations


def quarantine_import(
    *, run_id: str, job_ids: Iterable[int], reason: str,
    ats_source_ids: Iterable[int] = (), connection=None,
) -> dict[str, object]:
    """Cancel only untracked jobs from the named run; retain rows for audit."""
    jobs = sorted(set(job_ids))
    sources = sorted(set(ats_source_ids))
    if not run_id or not jobs or not reason.strip():
        raise ValueError("run_id, job_ids, and reason are required")
    owned = connection is None
    conn = connection or get_connection()
    try:
        apply_migrations(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        markers = ",".join("?" for _ in jobs)
        rows = conn.execute(
            f"""SELECT j.job_id, j.company_id, j.discovery_run_id,
                       q.status AS queue_status, t.tracked_id
                FROM job_postings j
                LEFT JOIN job_evaluation_queue q USING(job_id)
                LEFT JOIN tracked_jobs t USING(job_id)
                WHERE j.job_id IN ({markers})""",
            jobs,
        ).fetchall()
        if {int(row["job_id"]) for row in rows} != set(jobs):
            raise ValueError("some job IDs do not exist")
        if any(row["discovery_run_id"] != run_id for row in rows):
            raise ValueError("all jobs must belong to the specified discovery run")
        if any(row["tracked_id"] is not None or row["queue_status"] in {"claimed", "completed"} for row in rows):
            raise ValueError("tracked, claimed, or evaluated jobs require manual review")
        company_ids = {int(row["company_id"]) for row in rows}
        if sources:
            source_markers = ",".join("?" for _ in sources)
            source_rows = conn.execute(
                f"SELECT ats_source_id, company_id FROM employer_ats_sources WHERE ats_source_id IN ({source_markers})",
                sources,
            ).fetchall()
            if {int(row["ats_source_id"]) for row in source_rows} != set(sources) or any(
                int(row["company_id"]) not in company_ids for row in source_rows
            ):
                raise ValueError("ATS sources must belong to quarantined job employers")

        conn.execute(f"UPDATE job_postings SET active=0 WHERE job_id IN ({markers})", jobs)
        conn.execute(
            f"""UPDATE job_evaluation_queue
                SET status='cancelled', defer_reason=?, last_error=?,
                    lease_owner=NULL, lease_expires_at=NULL, updated_at=CURRENT_TIMESTAMP
                WHERE job_id IN ({markers})""",
            (reason, reason, *jobs),
        )
        if sources:
            conn.execute(
                f"""UPDATE employer_ats_sources SET enabled=0, status='error',
                    last_error=?, updated_at=CURRENT_TIMESTAMP
                    WHERE ats_source_id IN ({source_markers})""",
                (reason, *sources),
            )
        result: dict[str, object] = {
            "run_id": run_id, "job_ids": jobs, "ats_source_ids": sources,
            "reason": reason,
        }
        conn.execute(
            "INSERT INTO runs (run_type, completed_at, notes) VALUES ('import_quality_review', CURRENT_TIMESTAMP, ?)",
            (json.dumps(result, sort_keys=True),),
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        if owned:
            conn.close()
