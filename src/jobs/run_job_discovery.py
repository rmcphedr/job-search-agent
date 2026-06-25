"""Run job discovery across company career pages."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.database.db import get_project_root
from src.database.import_inventory import get_inventory_path
from src.discovery.link_utils import clean_url
from src.jobs.discovery_config import (
    DiscoveryConfig,
    load_discovery_config,
    normalize_size_tier,
    resolve_discovery_config_for_company,
)
from src.jobs.filter_jobs import filter_jobs
from src.jobs.job_extractors import extract_jobs_from_career_page
from src.jobs.job_models import JobCandidate
from src.jobs.llm_fit_discovery import apply_llm_fit_scores
from src.jobs.save_jobs import SaveJobsResult, save_jobs
from src.llm.job_fit import build_company_context_from_inventory_row

logger = logging.getLogger(__name__)

DEFAULT_EXPORT = get_project_root() / "outputs" / "job_discovery_results.csv"


@dataclass
class CompanyDiscoveryStats:
    company_name: str
    company_id: int | None = None
    size_tier: str = "default"
    raw_jobs_found: int = 0
    prescreened_jobs: int = 0
    triaged_jobs: int = 0
    enriched_jobs: int = 0
    llm_fit_scored: int = 0
    jobs_saved: int = 0
    status: str = "ok"
    search_strategy: str | None = None
    notes: str = ""


@dataclass
class RunSummary:
    companies_checked: int = 0
    companies_with_career_pages: int = 0
    companies_with_errors: int = 0
    raw_jobs_found: int = 0
    prescreened_jobs: int = 0
    triaged_jobs: int = 0
    enriched_jobs: int = 0
    llm_fit_scored: int = 0
    jobs_passing_filter: int = 0
    new_jobs_inserted: int = 0
    duplicates_skipped: int = 0
    updated_jobs: int = 0
    export_path: str = ""
    rows: list[dict[str, object]] = field(default_factory=list)
    company_stats: list[CompanyDiscoveryStats] = field(default_factory=list)


def _is_valid_career_page(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = str(value).strip()
    if not text or text.upper() == "NOT FOUND":
        return False
    return bool(clean_url(text))


def _company_matches(name: str, company_filter: str) -> bool:
    target = company_filter.strip().lower()
    return name.strip().lower() == target or target in name.strip().lower()


def run_job_discovery(
    *,
    limit: int | None = None,
    company: str | None = None,
    dry_run: bool = False,
    force_refresh: bool = False,
    sleep_seconds: float = 0.0,
    min_keyword_score: float | None = None,
    export_path: Path = DEFAULT_EXPORT,
    discovery_config: DiscoveryConfig | None = None,
) -> RunSummary:
    base_config = discovery_config or load_discovery_config()
    inventory_path = get_inventory_path()
    frame = pd.read_csv(inventory_path, dtype=str)
    summary = RunSummary()
    all_filtered_jobs: list[JobCandidate] = []

    for _, row in frame.iterrows():
        company_name = str(row.get("company_name", "")).strip()
        if not company_name:
            continue
        if company and not _company_matches(company_name, company):
            continue

        summary.companies_checked += 1
        career_page_raw = row.get("career_page", "")
        if not _is_valid_career_page(career_page_raw):
            continue

        if limit is not None and summary.companies_with_career_pages >= limit:
            break

        summary.companies_with_career_pages += 1
        career_page = clean_url(str(career_page_raw))
        company_id = None
        if str(row.get("company_id", "")).strip().isdigit():
            company_id = int(str(row.get("company_id")).strip())

        company_config = resolve_discovery_config_for_company(
            base_config,
            company_size=row.get("size"),
            company_name=company_name,
        )
        effective_min_score = (
            min_keyword_score
            if min_keyword_score is not None
            else company_config.prescreen.min_keyword_score
        )
        size_tier = normalize_size_tier(row.get("size"))
        if size_tier == "default" and "corporation" in company_name.lower():
            size_tier = "large"

        logger.info(
            "Extracting jobs for %s from %s (size_tier=%s)",
            company_name,
            career_page,
            size_tier,
        )
        extraction = extract_jobs_from_career_page(
            career_page or "",
            company_name=company_name,
            company_id=company_id,
            discovery_config=company_config,
        )

        company_stats = CompanyDiscoveryStats(
            company_name=company_name,
            company_id=company_id,
            size_tier=size_tier,
            search_strategy=str(extraction.get("search_strategy") or "") or None,
            notes=str(extraction.get("notes") or ""),
        )

        if extraction["status"] != "OK":
            summary.companies_with_errors += 1
            company_stats.status = "error"

        raw_jobs: list[JobCandidate] = extraction["jobs"]  # type: ignore[assignment]
        raw_count = int(extraction.get("raw_jobs_found") or 0)
        prescreened_count = int(extraction.get("prescreened_jobs") or 0)
        triaged_count = int(extraction.get("triaged_jobs") or 0)
        enriched_count = int(extraction.get("enriched_jobs") or 0)

        summary.raw_jobs_found += raw_count
        summary.prescreened_jobs += prescreened_count
        summary.triaged_jobs += triaged_count
        summary.enriched_jobs += enriched_count

        company_stats.raw_jobs_found = raw_count
        company_stats.prescreened_jobs = prescreened_count
        company_stats.triaged_jobs = triaged_count
        company_stats.enriched_jobs = enriched_count

        filtered_jobs = filter_jobs(
            raw_jobs,
            min_keyword_score=effective_min_score,
            title_only=False,
            location_filters=company_config.location_filters,
            require_location_match=company_config.prescreen.require_location_match,
            location_score_boost=company_config.prescreen.location_score_boost,
        )
        filtered_jobs = filtered_jobs[: company_config.budgets.max_jobs_saved_per_company]

        company_context = build_company_context_from_inventory_row(dict(row))
        filtered_jobs, fit_scored = apply_llm_fit_scores(
            filtered_jobs,
            company_context=company_context,
            enabled=company_config.llm_fit.enabled,
            max_scores=company_config.budgets.max_llm_fit_scores,
        )
        summary.llm_fit_scored += fit_scored
        company_stats.llm_fit_scored = fit_scored

        summary.jobs_passing_filter += len(filtered_jobs)
        company_stats.jobs_saved = len(filtered_jobs)
        if company_stats.status == "ok" and not filtered_jobs:
            company_stats.status = "no_jobs"
        all_filtered_jobs.extend(filtered_jobs)
        summary.company_stats.append(company_stats)

        for job in filtered_jobs:
            summary.rows.append(
                {
                    "company_id": company_id,
                    "company_name": company_name,
                    "size_tier": size_tier,
                    "career_page": career_page,
                    "provider": extraction.get("provider"),
                    "search_strategy": extraction.get("search_strategy"),
                    "status": extraction.get("status"),
                    "raw_jobs_found": raw_count,
                    "prescreened_jobs": prescreened_count,
                    "triaged_jobs": triaged_count,
                    "enriched_jobs": enriched_count,
                    "llm_fit_scored": fit_scored,
                    "title": job.title,
                    "location": job.location,
                    "url": job.url,
                    "keyword_score": job.keyword_score,
                    "matched_keywords": "; ".join(job.matched_keywords),
                    "notes": extraction.get("notes"),
                }
            )

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    export_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summary.rows).to_csv(export_path, index=False)
    summary.export_path = str(export_path)

    if not dry_run and all_filtered_jobs:
        save_result: SaveJobsResult = save_jobs(all_filtered_jobs, force_refresh=force_refresh)
        summary.new_jobs_inserted = save_result.inserted
        summary.duplicates_skipped = save_result.duplicates_skipped
        summary.updated_jobs = save_result.updated

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover jobs from company career pages.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N companies.")
    parser.add_argument("--company", type=str, default=None, help="Process one company by name.")
    parser.add_argument("--dry-run", action="store_true", help="Do not insert jobs into SQLite.")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Update existing duplicate jobs instead of skipping them.",
    )
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between companies.")
    parser.add_argument(
        "--min-keyword-score",
        type=float,
        default=None,
        help="Minimum keyword score required to save a job (defaults to config/job_discovery.yaml).",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=DEFAULT_EXPORT,
        help="Path for the run summary CSV export.",
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

    summary = run_job_discovery(
        limit=args.limit,
        company=args.company,
        dry_run=args.dry_run,
        force_refresh=args.force_refresh,
        sleep_seconds=args.sleep,
        min_keyword_score=args.min_keyword_score,
        export_path=args.export,
    )

    print("Job discovery summary:")
    print(f"  companies checked: {summary.companies_checked}")
    print(f"  companies with career pages: {summary.companies_with_career_pages}")
    print(f"  companies with errors: {summary.companies_with_errors}")
    print(f"  raw jobs found: {summary.raw_jobs_found}")
    print(f"  jobs passing pre-screen: {summary.prescreened_jobs}")
    print(f"  jobs passing LLM triage: {summary.triaged_jobs}")
    print(f"  jobs enriched: {summary.enriched_jobs}")
    print(f"  jobs LLM fit scored: {summary.llm_fit_scored}")
    print(f"  jobs passing keyword filter: {summary.jobs_passing_filter}")
    print(f"  new jobs inserted: {summary.new_jobs_inserted}")
    print(f"  duplicates skipped: {summary.duplicates_skipped}")
    print(f"  jobs updated: {summary.updated_jobs}")
    print(f"  output CSV: {summary.export_path}")
    if summary.company_stats:
        print("\nPer-company funnel:")
        for stats in summary.company_stats:
            print(
                f"  - {stats.company_name} ({stats.size_tier}): "
                f"raw={stats.raw_jobs_found}, pre-screen={stats.prescreened_jobs}, "
                f"triage={stats.triaged_jobs}, enriched={stats.enriched_jobs}, "
                f"llm_fit={stats.llm_fit_scored}, saved={stats.jobs_saved}"
            )
    if args.dry_run:
        print("Dry run enabled: SQLite job_postings was not updated.")


if __name__ == "__main__":
    main()
