"""CLI for registered employer ATS source discovery."""

from __future__ import annotations

import argparse

from src.jobs.employer_ats_discovery import run_employer_ats_discovery
from src.jobs.employer_ats_sources import SUPPORTED_ATS_PROVIDERS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover jobs from registered employer ATS sources."
    )
    parser.add_argument("--provider", choices=SUPPORTED_ATS_PROVIDERS)
    parser.add_argument("--company", help="Exact or partial employer name.")
    parser.add_argument("--dry-run", action="store_true", help="Do not register or save jobs.")
    parser.add_argument(
        "--no-sync", action="store_true", help="Do not discover sources before the run."
    )
    parser.add_argument(
        "--no-fetch-embedded",
        action="store_true",
        help="Only register direct ATS URLs; do not fetch career pages for embedded ATS links.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = run_employer_ats_discovery(
        provider=args.provider,
        company=args.company,
        sync_sources=not args.no_sync,
        dry_run=args.dry_run,
        fetch_embedded=not args.no_fetch_embedded,
    )
    print(
        f"ATS sources checked={summary.sources_checked} registered={summary.sources_registered} "
        f"raw={summary.raw_jobs_found} filtered={summary.jobs_after_filter} "
        f"inserted={summary.inserted} duplicates={summary.duplicates_skipped}"
        f" backfilled={summary.legacy_jobs_backfilled}"
    )
    for stats in summary.source_stats:
        detail = f" error={stats.error}" if stats.error else ""
        print(
            f"- {stats.provider}:{stats.company_name} status={stats.status} "
            f"raw={stats.raw_jobs} filtered={stats.filtered_jobs} inserted={stats.inserted}{detail}"
        )


if __name__ == "__main__":
    main()
