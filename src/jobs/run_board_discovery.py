"""CLI entry point for multi-board job discovery."""

from __future__ import annotations

import argparse
import logging
import sys

from src.jobs.board_discovery.runner import run_board_discovery


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover jobs from configured job boards (Canada-first).")
    parser.add_argument(
        "--boards",
        type=str,
        default="",
        help="Comma-separated source_id list (default: all enabled boards).",
    )
    parser.add_argument("--location", type=str, default="", help="Location filter (default: Canada).")
    parser.add_argument(
        "--queries",
        type=str,
        default="",
        help="Comma-separated search queries (default: config/job_keywords.yaml).",
    )
    parser.add_argument("--phase", type=int, default=None, help="Max implementation phase to include.")
    parser.add_argument("--dry-run", action="store_true", help="Search and filter without writing to SQLite.")
    parser.add_argument(
        "--no-ats-enrich",
        action="store_true",
        help="Skip ATS description enrichment for board listings.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    board_ids = [item.strip() for item in args.boards.split(",") if item.strip()] or None
    queries = [item.strip() for item in args.queries.split(",") if item.strip()] or None

    summary = run_board_discovery(
        board_ids=board_ids,
        location=args.location or None,
        queries=queries,
        phase=args.phase,
        dry_run=args.dry_run,
        enrich_ats=not args.no_ats_enrich,
    )

    print(f"Run ID: {summary.run_id}")
    print(f"Boards checked: {summary.boards_checked}")
    print(f"Raw jobs found: {summary.raw_jobs_found}")
    print(f"After keyword filter: {summary.jobs_after_filter}")
    if summary.dry_run:
        print("Dry run — no database writes.")
    else:
        print(f"Inserted: {summary.inserted}")
        print(f"Duplicates skipped: {summary.duplicates_skipped}")
        print(f"Companies created: {summary.companies_created}")

    for stats in summary.board_stats:
        line = f"  {stats.source_id}: queries={stats.queries_run} raw={stats.raw_jobs}"
        if stats.notes:
            line += f" ({stats.notes})"
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
