"""Synchronize and run registered employer ATS sources."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import pandas as pd

from src.careers.update_inventory_career_pages import get_inventory_path
from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.jobs.discovery_config import load_discovery_config
from src.jobs.employer_ats_adapters import extract_ats_jobs
from src.jobs.employer_ats_sources import (
    EmployerATSSource,
    backfill_legacy_ats_job_sources,
    identify_ats_source,
    list_ats_sources,
    update_ats_source_status,
    upsert_ats_source,
)
from src.jobs.filter_jobs import filter_jobs
from src.jobs.job_extractors import fetch_page
from src.jobs.job_models import JobCandidate
from src.jobs.job_url_utils import compute_content_hash
from src.jobs.save_jobs import save_jobs


@dataclass
class ATSSourceRunStats:
    ats_source_id: int
    company_name: str
    provider: str
    raw_jobs: int = 0
    filtered_jobs: int = 0
    inserted: int = 0
    duplicates_skipped: int = 0
    status: str = "not_run"
    error: str = ""


@dataclass
class ATSDiscoverySummary:
    run_id: str
    sources_checked: int = 0
    sources_registered: int = 0
    raw_jobs_found: int = 0
    jobs_after_filter: int = 0
    inserted: int = 0
    duplicates_skipped: int = 0
    legacy_jobs_backfilled: int = 0
    dry_run: bool = False
    source_stats: list[ATSSourceRunStats] = field(default_factory=list)


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _company_id_for_name(connection, company_name: str) -> int | None:
    row = connection.execute(
        "SELECT company_id FROM companies WHERE company_name = ? COLLATE NOCASE LIMIT 1;",
        (company_name,),
    ).fetchone()
    return int(row["company_id"]) if row else None


def discover_ats_sources(*, persist: bool = True, fetch_embedded: bool = True) -> int:
    """Register ATS sources found in inventory career pages and existing job URLs."""
    connection = get_connection()
    discovered: set[tuple[int, str, str]] = set()
    try:
        apply_migrations(connection)

        rows = connection.execute(
            """
            SELECT DISTINCT j.company_id, j.url
            FROM job_postings j
            WHERE j.url IS NOT NULL AND trim(j.url) != '';
            """
        ).fetchall()
        for row in rows:
            identified = identify_ats_source(str(row["url"]))
            if identified:
                provider, board_url, token = identified
                key = (int(row["company_id"]), provider, board_url)
                discovered.add(key)
                if persist:
                    upsert_ats_source(
                        connection,
                        company_id=key[0],
                        provider=provider,
                        board_url=board_url,
                        board_token=token,
                        discovery_method="existing_job_url",
                    )

        inventory_path = get_inventory_path()
        if inventory_path.exists():
            frame = pd.read_csv(inventory_path, dtype=str).fillna("")
            for _, row in frame.iterrows():
                company_name = str(row.get("company_name", "")).strip()
                career_page = str(row.get("career_page", "")).strip()
                if not company_name or not career_page or career_page.upper() == "NOT FOUND":
                    continue
                company_id = _company_id_for_name(connection, company_name)
                if company_id is None:
                    continue
                identified = identify_ats_source(career_page)
                if identified is None and fetch_embedded:
                    status, final_url, html = fetch_page(career_page)
                    if status in {200, 301, 302} and html:
                        identified = identify_ats_source(final_url, html)
                if identified:
                    provider, board_url, token = identified
                    key = (company_id, provider, board_url)
                    discovered.add(key)
                    if persist:
                        upsert_ats_source(
                            connection,
                            company_id=company_id,
                            provider=provider,
                            board_url=board_url,
                            board_token=token,
                            discovery_method="career_page",
                        )
        if persist:
            connection.commit()
        return len(discovered)
    finally:
        connection.close()


def _candidate(source: EmployerATSSource, job) -> JobCandidate:
    return JobCandidate(
        company_id=source.company_id,
        company_name=source.company_name,
        title=job.title,
        location=job.location,
        url=job.url,
        description=job.description,
        date_posted=job.date_posted,
        provider=source.provider,
        source_career_page=source.board_url,
        content_hash=compute_content_hash(job.title, job.description, job.url),
        notes=f"Registered {source.provider} employer ATS source",
    )


def _log_run(summary: ATSDiscoverySummary) -> None:
    payload = {
        "run_id": summary.run_id,
        "dry_run": summary.dry_run,
        "sources_checked": summary.sources_checked,
        "sources_registered": summary.sources_registered,
        "raw_jobs_found": summary.raw_jobs_found,
        "jobs_after_filter": summary.jobs_after_filter,
        "inserted": summary.inserted,
        "duplicates_skipped": summary.duplicates_skipped,
        "legacy_jobs_backfilled": summary.legacy_jobs_backfilled,
        "sources": [asdict(stats) for stats in summary.source_stats],
    }
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.execute(
            """INSERT INTO runs (run_type, completed_at, companies_checked, notes)
               VALUES ('employer_ats_discovery', CURRENT_TIMESTAMP, ?, ?);""",
            (summary.sources_checked, json.dumps(payload, separators=(",", ":"))),
        )
        connection.commit()
    finally:
        connection.close()


def run_employer_ats_discovery(
    *,
    provider: str | None = None,
    company: str | None = None,
    sync_sources: bool = True,
    dry_run: bool = False,
    fetch_embedded: bool = True,
) -> ATSDiscoverySummary:
    config = load_discovery_config()
    summary = ATSDiscoverySummary(run_id=_new_run_id(), dry_run=dry_run)
    if sync_sources:
        summary.sources_registered = discover_ats_sources(
            persist=not dry_run,
            fetch_embedded=fetch_embedded,
        )
        if not dry_run:
            connection = get_connection()
            try:
                summary.legacy_jobs_backfilled = backfill_legacy_ats_job_sources(connection)
                connection.commit()
            finally:
                connection.close()

    connection = get_connection()
    try:
        sources = list_ats_sources(connection, provider=provider, company=company)
    finally:
        connection.close()

    for source in sources:
        stats = ATSSourceRunStats(
            ats_source_id=source.ats_source_id,
            company_name=source.company_name,
            provider=source.provider,
        )
        summary.sources_checked += 1
        try:
            raw = extract_ats_jobs(source.provider, source.board_url, "")
            candidates = [_candidate(source, job) for job in raw]
            filtered = filter_jobs(
                candidates,
                min_keyword_score=config.prescreen.min_keyword_score,
                title_only=config.prescreen.title_only,
                location_filters=config.location_filters,
                require_location_match=config.prescreen.require_location_match,
                location_score_boost=config.prescreen.location_score_boost,
            )[: config.budgets.max_jobs_saved_per_company]
            stats.raw_jobs = len(candidates)
            stats.filtered_jobs = len(filtered)
            stats.status = "healthy" if candidates else "empty"
            summary.raw_jobs_found += len(candidates)
            summary.jobs_after_filter += len(filtered)

            if not dry_run and filtered:
                saved = save_jobs(
                    filtered,
                    pending_evaluation=True,
                    source_board=source.provider,
                    discovery_run_id=summary.run_id,
                )
                stats.inserted = saved.inserted
                stats.duplicates_skipped = saved.duplicates_skipped
                summary.inserted += saved.inserted
                summary.duplicates_skipped += saved.duplicates_skipped
        except Exception as exc:
            stats.status = "error"
            stats.error = str(exc)

        if not dry_run:
            connection = get_connection()
            try:
                update_ats_source_status(
                    connection,
                    source.ats_source_id,
                    status=stats.status,
                    error=stats.error or None,
                )
                connection.commit()
            finally:
                connection.close()
        summary.source_stats.append(stats)

    _log_run(summary)
    return summary
