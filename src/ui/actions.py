"""Dashboard action wrappers around existing backend pipelines."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from src.careers.update_inventory_career_pages import run_update
from src.database.db import get_connection
from src.jobs.run_job_discovery import RunSummary, run_job_discovery

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class CareerDiscoveryResult:
    companies_checked: int = 0
    career_pages_found: int = 0
    career_pages_not_found: int = 0
    errors: int = 0
    skipped: int = 0
    company_results: list[dict[str, object]] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class JobDiscoveryActionResult:
    companies_checked: int = 0
    jobs_found: int = 0
    jobs_inserted: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    company_results: dict[str, dict[str, object]] = field(default_factory=dict)
    error_message: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_run(
    *,
    run_type: str,
    companies_checked: int,
    notes: dict[str, object],
) -> None:
    try:
        connection = get_connection()
        try:
            connection.execute(
                """
                INSERT INTO runs (run_type, started_at, completed_at, companies_checked, notes)
                VALUES (?, ?, ?, ?, ?);
                """,
                (
                    run_type,
                    _utc_now(),
                    _utc_now(),
                    companies_checked,
                    json.dumps(notes),
                ),
            )
            connection.commit()
        finally:
            connection.close()
    except Exception as exc:
        logger.warning("Failed to record run history: %s", exc)


def run_career_page_discovery(
    selected_companies: list[str],
    *,
    force: bool = False,
    sleep_seconds: float = 1.0,
    progress_callback: ProgressCallback | None = None,
) -> CareerDiscoveryResult:
    """Run career page discovery for selected companies."""
    result = CareerDiscoveryResult()
    if not selected_companies:
        result.error_message = "No companies selected."
        return result

    total = len(selected_companies)
    for index, company_name in enumerate(selected_companies, start=1):
        if progress_callback is not None:
            progress_callback(index, total, f"Checking company {index} of {total}: {company_name}")

        try:
            frame = run_update(
                company=company_name,
                force=force,
                dry_run=False,
                sleep_seconds=sleep_seconds if index < total else 0.0,
            )
        except Exception as exc:
            logger.exception("Career page discovery failed for %s", company_name)
            result.errors += 1
            result.companies_checked += 1
            result.company_results.append(
                {
                    "company_name": company_name,
                    "career_page": "NOT FOUND",
                    "career_page_status": "ERROR",
                    "error": str(exc),
                }
            )
            continue

        if frame.empty:
            result.skipped += 1
            result.company_results.append(
                {
                    "company_name": company_name,
                    "career_page_status": "SKIPPED",
                    "notes": "Already checked or no matching row",
                }
            )
            continue

        row = frame.iloc[0]
        result.companies_checked += 1
        career_page = str(row.get("career_page", "")).strip()
        status = str(row.get("career_page_status", "")).strip().upper()
        result.company_results.append(dict(row))

        if status == "ERROR":
            result.errors += 1
        elif career_page.upper() == "NOT FOUND":
            result.career_pages_not_found += 1
        else:
            result.career_pages_found += 1

    _record_run(
        run_type="career_discovery",
        companies_checked=result.companies_checked,
        notes={
            "summary": {
                "career_pages_found": result.career_pages_found,
                "career_pages_not_found": result.career_pages_not_found,
                "errors": result.errors,
                "skipped": result.skipped,
            },
            "companies": result.company_results,
        },
    )
    return result


def run_job_discovery_action(
    selected_companies: list[str],
    *,
    sleep_seconds: float = 1.0,
    progress_callback: ProgressCallback | None = None,
) -> JobDiscoveryActionResult:
    """Run job discovery for selected companies and insert results into SQLite."""
    result = JobDiscoveryActionResult()
    if not selected_companies:
        result.error_message = "No companies selected."
        return result

    total = len(selected_companies)
    for index, company_name in enumerate(selected_companies, start=1):
        if progress_callback is not None:
            progress_callback(index, total, f"Discovering jobs {index} of {total}: {company_name}")

        try:
            summary: RunSummary = run_job_discovery(
                company=company_name,
                dry_run=False,
                sleep_seconds=sleep_seconds if index < total else 0.0,
            )
        except Exception as exc:
            logger.exception("Job discovery failed for %s", company_name)
            result.errors += 1
            result.companies_checked += 1
            result.company_results[company_name] = {
                "status": "error",
                "message": str(exc),
                "raw_jobs": 0,
                "filtered_jobs": 0,
                "inserted": 0,
            }
            continue

        result.companies_checked += summary.companies_with_career_pages
        result.jobs_found += summary.jobs_passing_filter
        result.jobs_inserted += summary.new_jobs_inserted
        result.duplicates_skipped += summary.duplicates_skipped
        result.errors += summary.companies_with_errors

        if summary.companies_with_career_pages == 0:
            result.company_results[company_name] = {
                "status": "skipped",
                "message": "No valid career page",
                "raw_jobs": 0,
                "filtered_jobs": 0,
                "inserted": 0,
            }
            continue

        if summary.companies_with_errors > 0:
            status = "error"
        elif summary.jobs_passing_filter == 0:
            status = "no_jobs"
        else:
            status = "ok"

        result.company_results[company_name] = {
            "status": status,
            "raw_jobs": summary.raw_jobs_found,
            "filtered_jobs": summary.jobs_passing_filter,
            "inserted": summary.new_jobs_inserted,
            "duplicates_skipped": summary.duplicates_skipped,
        }

    _record_run(
        run_type="job_discovery",
        companies_checked=result.companies_checked,
        notes={
            "summary": {
                "jobs_found": result.jobs_found,
                "jobs_inserted": result.jobs_inserted,
                "duplicates_skipped": result.duplicates_skipped,
                "errors": result.errors,
            },
            "companies": result.company_results,
        },
    )
    return result


def refresh_data() -> None:
    """Clear cached dashboard data so loaders fetch fresh CSV/DB contents."""
    import streamlit as st

    st.cache_data.clear()
