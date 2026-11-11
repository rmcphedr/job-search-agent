"""Bounded, cron-friendly discovery entry point; scoring remains an agent task."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd

from src.database.db import get_connection
from src.database.import_inventory import get_inventory_path
from src.jobs.board_discovery.config import load_board_sources_config
from src.jobs.board_discovery.runner import run_board_discovery
from src.jobs.discovery_config import load_discovery_config
from src.jobs.employer_ats_discovery import run_employer_ats_discovery
from src.jobs.run_job_discovery import _is_valid_career_page, run_job_discovery


def _career_offset(limit: int) -> int:
    """Rotate bounded career scans across inventory rows on successive days."""
    frame = pd.read_csv(get_inventory_path(), dtype=str)
    count = sum(_is_valid_career_page(value) for value in frame.get("career_page", []))
    return (datetime.now(timezone.utc).date().toordinal() * limit) % count if count else 0


def _ready_jobs(run_ids: list[str]) -> list[dict[str, object]]:
    if not run_ids:
        return []
    conn = get_connection()
    try:
        markers = ",".join("?" for _ in run_ids)
        rows = conn.execute(
            f"""SELECT j.job_id, j.discovery_run_id, c.company_name, j.title,
                       j.location, j.keyword_score, j.url
                FROM job_postings j JOIN companies c USING(company_id)
                JOIN job_evaluation_queue q USING(job_id)
                WHERE j.discovery_run_id IN ({markers}) AND j.active=1
                  AND j.evaluated_at IS NULL AND j.description_status='enriched'
                  AND j.description_checked_at IS NOT NULL AND q.status='queued'
                ORDER BY j.keyword_score DESC, j.date_found DESC""",
            run_ids,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def run_scheduled_discovery(
    *, dry_run: bool = False, include_careers: bool = False,
    career_limit: int = 25, all_boards: bool = False,
) -> dict[str, object]:
    """Run selected enabled boards and ATS sources, then report current-run jobs."""
    config = load_board_sources_config()
    board_ids = [
        board.source_id for board in config.boards
        if board.enabled and (all_boards or board.phase <= 2)
    ]
    http_board_ids = [
        board.source_id for board in config.boards
        if board.source_id in board_ids and getattr(board, "scrape_mode", "requests") != "playwright"
    ]
    browser_board_ids = [source_id for source_id in board_ids if source_id not in http_board_ids]
    runs: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    result: dict[str, object] = {
        "dry_run": dry_run,
        "board_scope": "all_enabled" if all_boards else "phase_1_2",
        "boards_selected": board_ids,
        "boards_unattempted": [],
        "boards_skipped": [
            {"source_id": board.source_id, "reason": "disabled" if not board.enabled else "outside_selected_phase"}
            for board in config.boards
            if board.source_id not in board_ids
        ],
    }
    scan_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    result["run_id"] = scan_run_id

    if board_ids:
        try:
            board = run_board_discovery(board_ids=board_ids, dry_run=dry_run, run_id=scan_run_id)
        except Exception as exc:
            if not browser_board_ids or not http_board_ids:
                raise
            errors.append(f"browser board group failed before import: {exc}")
            result["boards_unattempted"] = browser_board_ids
            board = run_board_discovery(board_ids=http_board_ids, dry_run=dry_run, run_id=scan_run_id)
        result["boards"] = {
            "run_id": board.run_id, "inserted": board.inserted,
            "sources": [
                {"source_id": item.source_id, "raw_jobs": item.raw_jobs,
                 "filtered_jobs": item.filtered_jobs, "queries_run": item.queries_run,
                 "notes": item.notes}
                for item in board.board_stats
            ],
        }
        errors.extend(f"{item.source_id}: {item.notes}" for item in board.board_stats if item.notes.startswith("error:"))
        warnings.extend(
            f"{item.source_id}: zero results; source coverage unverified"
            for item in board.board_stats
            if item.queries_run and item.raw_jobs == 0 and not item.notes.startswith("error:")
        )
        if not dry_run:
            runs.append(scan_run_id)

    ats = run_employer_ats_discovery(
        dry_run=dry_run, run_id=scan_run_id,
        max_embedded_fetches=20, max_sources=50,
    )
    result["ats"] = {
        "run_id": ats.run_id, "registered": ats.sources_registered,
        "sources_checked": ats.sources_checked, "inserted": ats.inserted,
    }
    errors.extend(f"{item.provider}:{item.company_name}: {item.error}" for item in ats.source_stats if item.error)
    if not dry_run:
        runs.append(scan_run_id)

    if include_careers:
        discovery = load_discovery_config()
        no_model = replace(
            discovery,
            llm_fit=replace(discovery.llm_fit, enabled=False),
            llm_triage=replace(discovery.llm_triage, enabled=False),
        )
        offset = _career_offset(career_limit)
        careers = run_job_discovery(
            limit=career_limit, dry_run=dry_run, discovery_config=no_model,
            discovery_run_id=scan_run_id,
            company_offset=offset,
        )
        result["careers"] = {
            "run_id": scan_run_id, "companies_checked": careers.companies_with_career_pages,
            "inserted": careers.new_jobs_inserted, "errors": careers.companies_with_errors,
            "offset": offset,
        }
        if careers.companies_with_errors:
            errors.append(f"career pages: {careers.companies_with_errors} company errors")
        if not dry_run:
            runs.append(scan_run_id)

    result["discovery_run_ids"] = list(dict.fromkeys(runs))
    result["evaluation_candidates"] = _ready_jobs(result["discovery_run_ids"]) if runs else []
    result["errors"] = errors
    result["warnings"] = warnings
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-careers", action="store_true")
    parser.add_argument("--all-boards", action="store_true", help="Scan every enabled board, including phase 3.")
    parser.add_argument("--career-limit", type=int, default=25)
    args = parser.parse_args(argv)
    if args.career_limit < 1:
        parser.error("--career-limit must be positive")
    result = run_scheduled_discovery(
        dry_run=args.dry_run, include_careers=args.include_careers,
        career_limit=args.career_limit, all_boards=args.all_boards,
    )
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
