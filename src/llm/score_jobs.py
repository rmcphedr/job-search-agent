"""Batch job fit scoring CLI."""

from __future__ import annotations

import argparse
import logging
import sqlite3
from dataclasses import dataclass, field

import pandas as pd

from src.database.db import get_database_path
from src.database.import_inventory import get_inventory_path
from src.llm.job_fit import build_company_context_from_inventory_row, score_job_safe
from src.llm.llm_client import LLMClientError, OllamaClient, load_llm_config
from src.llm.score_exports import job_result_to_row, upsert_job_fit_rows

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
ORDER BY c.company_name, j.title;
"""


@dataclass
class JobScoreSummary:
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


def score_jobs(
    *,
    limit: int | None = None,
    company: str | None = None,
    force_refresh: bool = False,
) -> JobScoreSummary:
    """Score jobs from SQLite and export results."""
    config = load_llm_config()
    batch_size = int(config.get("batch_size", 5))
    db_path = get_database_path()
    summary = JobScoreSummary()
    export_rows: list[dict[str, object]] = []

    if not db_path.exists():
        summary.errors += 1
        summary.error_messages.append(f"Database not found: {db_path}")
        return summary

    try:
        client = OllamaClient(config)
    except LLMClientError as exc:
        summary.errors += 1
        summary.error_messages.append(str(exc))
        return summary

    company_context_map = _load_company_context_map()

    try:
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        jobs = connection.execute(JOBS_QUERY).fetchall()
    except sqlite3.Error as exc:
        summary.errors += 1
        summary.error_messages.append(f"Failed to read jobs: {exc}")
        return summary
    finally:
        if "connection" in locals():
            connection.close()

    pending = 0
    for job_row in jobs:
        company_name = str(job_row["company_name"]).strip()
        if company and not _company_matches(company_name, company):
            continue
        if limit is not None and summary.jobs_processed >= limit:
            break

        summary.jobs_processed += 1
        job_record = {
            "title": job_row["title"],
            "company_name": company_name,
            "location": job_row["location"],
            "description": job_row["description"],
        }
        company_context = company_context_map.get(company_name.lower(), {})

        result, error = score_job_safe(
            job_record,
            company_context=company_context,
            client=client,
            force_refresh=force_refresh,
        )

        if error:
            summary.errors += 1
            summary.error_messages.append(f"{job_row['title']} ({company_name}): {error}")
            continue

        if result is None:
            summary.errors += 1
            continue

        summary.jobs_scored += 1
        export_rows.append(job_result_to_row(result))
        pending += 1

        if pending >= batch_size:
            path = upsert_job_fit_rows(export_rows)
            summary.export_path = str(path)
            export_rows.clear()
            pending = 0

    if export_rows:
        path = upsert_job_fit_rows(export_rows)
        summary.export_path = str(path)

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score job postings for candidate fit using local Ollama.")
    parser.add_argument("--limit", type=int, default=None, help="Score at most N jobs.")
    parser.add_argument("--company", type=str, default=None, help="Score jobs for one company by name.")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore cache and re-score with the LLM.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable informational logging.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    summary = score_jobs(
        limit=args.limit,
        company=args.company,
        force_refresh=args.force_refresh,
    )

    print("Job fit scoring summary:")
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
