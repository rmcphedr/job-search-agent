"""Batch job fit scoring CLI."""

from __future__ import annotations

import argparse
import logging
import sqlite3
from dataclasses import dataclass, field

import pandas as pd

from src.database.db import get_connection, get_database_path
from src.database.import_inventory import get_inventory_path
from src.llm.job_fit import build_company_context_from_inventory_row, score_job_safe
from src.llm.llm_client import LLMClientError, build_llm_client, hosted_provider, load_llm_config
from src.llm.schemas import JobFitResult
from src.llm.score_exports import job_result_to_row, upsert_job_fit_rows

MIN_DESCRIPTION_CHARS = 200

JOBS_QUERY = """
SELECT
    j.job_id,
    j.title,
    j.location,
    j.description,
    c.company_name
FROM job_postings AS j
INNER JOIN companies AS c ON j.company_id = c.company_id
WHERE j.active = 1
  AND length(trim(COALESCE(j.description, ''))) >= ?
  AND (? IS NULL OR datetime(j.date_found) >= datetime('now', ?))
  AND (? OR j.fit_score IS NULL)
ORDER BY datetime(j.date_found) DESC, c.company_name, j.title;
"""


@dataclass
class JobScoreSummary:
    jobs_selected: int = 0
    jobs_processed: int = 0
    jobs_scored: int = 0
    errors: int = 0
    export_path: str = ""
    error_messages: list[str] = field(default_factory=list)


def _company_matches(name: str, company_filter: str) -> bool:
    target = company_filter.strip().lower()
    return name.strip().lower() == target or target in name.strip().lower()


def _load_company_context_map() -> dict[str, dict[str, str]]:
    inventory_path = get_inventory_path()
    if not inventory_path.exists():
        return {}

    frame = pd.read_csv(inventory_path, dtype=str)
    context_map: dict[str, dict[str, str]] = {}
    for _, row in frame.iterrows():
        name = str(row.get("company_name", "")).strip()
        if not name:
            continue
        context_map[name.lower()] = build_company_context_from_inventory_row(row.to_dict())
    return context_map


def load_jobs_to_score(
    connection: sqlite3.Connection,
    *,
    since_days: int | None,
    min_description_chars: int,
    include_scored: bool,
) -> list[sqlite3.Row]:
    """Return active jobs with a real description, optionally limited by age."""
    window = None if since_days is None else f"-{int(since_days)} days"
    return list(
        connection.execute(
            JOBS_QUERY,
            (min_description_chars, window, window, 1 if include_scored else 0),
        ).fetchall()
    )


def persist_job_fit(connection: sqlite3.Connection, job_id: int, result: JobFitResult) -> None:
    """Write a validated fit result onto the job and close an unclaimed queue item."""
    payload = result.model_copy(update={"job_id": job_id})
    connection.execute(
        """
        UPDATE job_postings
        SET fit_score = ?, fit_reason = ?, fit_details = ?, evaluated_at = datetime('now')
        WHERE job_id = ?;
        """,
        (payload.fit_score, payload.why_fit, payload.model_dump_json(), job_id),
    )
    queue_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'job_evaluation_queue';"
    ).fetchone()
    if queue_exists is None:
        return
    connection.execute(
        """
        UPDATE job_evaluation_queue
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            lease_owner = NULL,
            lease_expires_at = NULL,
            last_error = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE job_id = ? AND status IN ('queued', 'deferred', 'failed');
        """,
        (job_id,),
    )


def score_jobs(
    *,
    limit: int | None = None,
    company: str | None = None,
    since_days: int | None = None,
    force_refresh: bool = False,
    progress: bool = False,
) -> JobScoreSummary:
    """Score jobs from SQLite, store the fit on each job, and export a CSV."""
    config = load_llm_config()
    batch_size = int(config.get("batch_size", 5))
    min_description_chars = int(config.get("min_description_chars", MIN_DESCRIPTION_CHARS))
    db_path = get_database_path()
    summary = JobScoreSummary()
    export_rows: list[dict[str, object]] = []

    if hosted_provider(config) and limit is None and since_days is None and not company:
        summary.errors += 1
        summary.error_messages.append(
            "Hosted scoring needs a bound. Pass --since-days 2, --limit N, or --company NAME."
        )
        return summary

    if not db_path.exists():
        summary.errors += 1
        summary.error_messages.append(f"Database not found: {db_path}")
        return summary

    try:
        client = build_llm_client(config)
    except LLMClientError as exc:
        summary.errors += 1
        summary.error_messages.append(str(exc))
        return summary

    company_context_map = _load_company_context_map()
    connection = get_connection(db_path)
    try:
        jobs = load_jobs_to_score(
            connection,
            since_days=since_days,
            min_description_chars=min_description_chars,
            include_scored=force_refresh,
        )
    except sqlite3.Error as exc:
        summary.errors += 1
        summary.error_messages.append(f"Failed to read jobs: {exc}")
        connection.close()
        return summary

    selected = []
    for job_row in jobs:
        company_name = str(job_row["company_name"]).strip()
        if company and not _company_matches(company_name, company):
            continue
        selected.append(job_row)
        if limit is not None and len(selected) >= limit:
            break
    summary.jobs_selected = len(selected)

    pending = 0
    try:
        for job_row in selected:
            company_name = str(job_row["company_name"]).strip()
            summary.jobs_processed += 1
            if progress:
                print(f"[{summary.jobs_processed}/{summary.jobs_selected}] {job_row['title']} ({company_name})")

            job_record = {
                "title": job_row["title"],
                "company_name": company_name,
                "location": job_row["location"],
                "description": job_row["description"],
            }
            company_context = company_context_map.get(company_name.lower(), {})
            try:
                result, error = score_job_safe(
                    job_record,
                    company_context=company_context,
                    client=client,
                    force_refresh=force_refresh,
                )
            except Exception as exc:
                summary.errors += 1
                summary.error_messages.append(f"{job_row['title']} ({company_name}): {exc}")
                continue
            if error or result is None:
                summary.errors += 1
                summary.error_messages.append(f"{job_row['title']} ({company_name}): {error or 'no result'}")
                continue

            stored = result.model_copy(update={"job_id": int(job_row["job_id"])})
            persist_job_fit(connection, int(job_row["job_id"]), stored)
            connection.commit()
            summary.jobs_scored += 1
            if progress:
                print(f"  fit {stored.fit_score:.1f}")
            export_rows.append(job_result_to_row(stored))
            pending += 1

            if pending >= batch_size:
                path = upsert_job_fit_rows(export_rows)
                summary.export_path = str(path)
                export_rows.clear()
                pending = 0
    finally:
        connection.close()

    if export_rows:
        path = upsert_job_fit_rows(export_rows)
        summary.export_path = str(path)

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score job postings against the candidate profile using config/llm.yaml."
    )
    parser.add_argument("--limit", type=int, default=None, help="Score at most N jobs.")
    parser.add_argument("--company", type=str, default=None, help="Score jobs for one company by name.")
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Score jobs found in the last N days.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore cache and re-score jobs that already have a fit score.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable informational logging.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.since_days is not None and args.since_days < 1:
        parser.error("--since-days must be at least 1")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    summary = score_jobs(
        limit=args.limit,
        company=args.company,
        since_days=args.since_days,
        force_refresh=args.force_refresh,
        progress=True,
    )

    print("Job fit scoring summary:")
    print(f"  jobs selected: {summary.jobs_selected}")
    print(f"  jobs processed: {summary.jobs_processed}")
    print(f"  jobs scored: {summary.jobs_scored}")
    print(f"  errors: {summary.errors}")
    if summary.export_path:
        print(f"  export CSV: {summary.export_path}")
    if summary.error_messages:
        print("  error details:")
        for message in summary.error_messages[:10]:
            print(f"    - {message}")


if __name__ == "__main__":
    main()
