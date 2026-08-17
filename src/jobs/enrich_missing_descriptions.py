"""Backfill missing job descriptions, prioritizing the Review inbox."""

from __future__ import annotations

import argparse
import logging
from contextlib import nullcontext
from dataclasses import dataclass

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.jobs.description_enrichment import (
    BROWSER_ENRICHMENT_SOURCES,
    DescriptionEnrichmentResult,
    apply_enrichment_result,
    enrich_description,
    mark_job_expired,
)
from src.jobs.board_discovery.playwright_client import PlaywrightBrowserClient, playwright_available

logger = logging.getLogger(__name__)


@dataclass
class BackfillSummary:
    selected: int = 0
    enriched: int = 0
    expired: int = 0
    not_found: int = 0
    errors: int = 0


def list_missing_description_jobs(
    *,
    limit: int = 25,
    source: str | None = None,
    only_review_inbox: bool = False,
    only_tracked: bool = False,
    retry_failed: bool = False,
) -> list[dict]:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        clauses = [
            "j.active = 1",
            "(j.description IS NULL OR TRIM(j.description) = '' OR LOWER(TRIM(j.description)) = 'nan')",
        ]
        params: list[object] = []
        if source:
            clauses.append("COALESCE(j.source_board, 'company_site') = ?")
            params.append(source)
        if not retry_failed:
            clauses.append("COALESCE(j.description_status, '') NOT IN ('not_found', 'error', 'expired')")
        if only_review_inbox:
            clauses.extend(
                (
                    "t.job_id IS NULL",
                    "COALESCE(r.decision, '') IN ('', 'maybe')",
                    "j.fit_score >= 7.0",
                )
            )
        if only_tracked:
            clauses.append("t.job_id IS NOT NULL")
        params.append(limit)
        rows = connection.execute(
            f"""
            SELECT j.*, c.company_name, r.decision AS review_decision,
                   CASE
                     WHEN t.job_id IS NULL
                       AND COALESCE(r.decision, '') IN ('', 'maybe')
                       AND j.fit_score >= 7.0 THEN 0
                     WHEN t.job_id IS NULL
                       AND COALESCE(r.decision, '') IN ('', 'maybe') THEN 1
                     ELSE 2
                   END AS enrichment_priority
            FROM job_postings AS j
            JOIN companies AS c ON c.company_id = j.company_id
            LEFT JOIN tracked_jobs AS t ON t.job_id = j.job_id
            LEFT JOIN job_reviews AS r ON r.job_id = j.job_id
            WHERE {' AND '.join(clauses)}
            ORDER BY enrichment_priority, j.fit_score IS NULL, j.fit_score DESC,
                     j.keyword_score DESC, j.date_found DESC
            LIMIT ?;
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def run_backfill(
    *,
    limit: int = 25,
    source: str | None = None,
    only_review_inbox: bool = False,
    only_tracked: bool = False,
    retry_failed: bool = False,
    dry_run: bool = False,
    browser_enrichment: bool = True,
) -> BackfillSummary:
    jobs = list_missing_description_jobs(
        limit=limit,
        source=source,
        only_review_inbox=only_review_inbox,
        only_tracked=only_tracked,
        retry_failed=retry_failed,
    )
    summary = BackfillSummary(selected=len(jobs))
    needs_browser = browser_enrichment and any(
        str(job.get("source_board") or "").casefold() in BROWSER_ENRICHMENT_SOURCES
        for job in jobs
    )
    if needs_browser and not playwright_available():
        raise RuntimeError("Browser enrichment requires Playwright and Chromium.")
    browser_context = PlaywrightBrowserClient() if needs_browser and not dry_run else nullcontext()

    with browser_context as browser:
        for job in jobs:
            if dry_run:
                print(
                    f"{job['job_id']}\tpriority={job['enrichment_priority']}\t"
                    f"{job['company_name']}\t{job['title']}\t{job.get('source_board') or 'company_site'}"
                )
                continue
            try:
                result = enrich_description(job, browser=browser)
                apply_enrichment_result(int(job["job_id"]), result)
                if result.status == "enriched":
                    summary.enriched += 1
                elif result.status == "expired":
                    summary.expired += 1
                elif result.status == "error":
                    summary.errors += 1
                else:
                    summary.not_found += 1
            except Exception as exc:
                logger.exception("Description enrichment failed for job %s", job["job_id"])
                summary.errors += 1
                apply_enrichment_result(
                    int(job["job_id"]),
                    DescriptionEnrichmentResult(status="error", error=str(exc)),
                )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--source", default="", help="Filter by source_board.")
    parser.add_argument("--only-review-inbox", action="store_true")
    parser.add_argument("--only-tracked", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-browser", action="store_true", help="Disable Playwright enrichment for LinkedIn and Eluta.")
    parser.add_argument("--mark-expired", type=int, metavar="JOB_ID")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.only_review_inbox and args.only_tracked:
        parser.error("--only-review-inbox and --only-tracked cannot be combined")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    if args.mark_expired is not None:
        mark_job_expired(args.mark_expired)
        print(f"Marked job {args.mark_expired} expired.")
        return 0

    summary = run_backfill(
        limit=args.limit,
        source=args.source or None,
        only_review_inbox=args.only_review_inbox,
        only_tracked=args.only_tracked,
        retry_failed=args.retry_failed,
        dry_run=args.dry_run,
        browser_enrichment=not args.no_browser,
    )
    print(
        f"Selected: {summary.selected} | Enriched: {summary.enriched} | "
        f"Expired: {summary.expired} | Not found: {summary.not_found} | Errors: {summary.errors}"
    )
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
