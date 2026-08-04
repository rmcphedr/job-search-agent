"""Orchestrate multi-board job discovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.jobs.board_discovery.ats_enrich import enrich_ats_job_descriptions
from src.jobs.board_discovery.config import BoardSource, get_enabled_boards, load_board_sources_config
from src.jobs.board_discovery.http import BoardHttpClient, is_persistent_board_error
from src.jobs.board_discovery.registry import get_adapter
from src.jobs.discovery_config import load_discovery_config
from src.jobs.filter_jobs import filter_jobs
from src.jobs.job_models import JobCandidate
from src.jobs.save_jobs import SaveJobsResult, save_jobs

logger = logging.getLogger(__name__)


@dataclass
class BoardRunStats:
    source_id: str
    queries_run: int = 0
    raw_jobs: int = 0
    filtered_jobs: int = 0
    notes: str = ""


@dataclass
class BoardDiscoverySummary:
    run_id: str
    boards_checked: int = 0
    raw_jobs_found: int = 0
    jobs_after_filter: int = 0
    inserted: int = 0
    duplicates_skipped: int = 0
    companies_created: int = 0
    board_stats: list[BoardRunStats] = field(default_factory=list)
    dry_run: bool = False


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _log_run(summary: BoardDiscoverySummary, notes: str) -> None:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO runs (run_type, completed_at, companies_checked, notes)
            VALUES (?, CURRENT_TIMESTAMP, ?, ?);
            """,
            (
                "board_discovery",
                summary.boards_checked,
                notes,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _dedupe_candidates(candidates: list[JobCandidate]) -> list[JobCandidate]:
    seen: set[str] = set()
    unique: list[JobCandidate] = []
    for candidate in candidates:
        key = (candidate.url or "", candidate.title.lower(), candidate.company_name.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def run_board_discovery(
    *,
    board_ids: list[str] | None = None,
    location: str | None = None,
    queries: list[str] | None = None,
    phase: int | None = None,
    dry_run: bool = False,
    enrich_ats: bool = True,
) -> BoardDiscoverySummary:
    config = load_board_sources_config()
    discovery_config = load_discovery_config()
    defaults = config.defaults

    resolved_location = location or str(defaults.get("location", "Canada"))
    search_queries = queries or discovery_config.search_queries
    max_pages = int(defaults.get("max_pages_per_query", 3))
    delay_ms = int(defaults.get("request_delay_ms", 1500))
    min_keyword_score = float(defaults.get("min_keyword_score", discovery_config.prescreen.min_keyword_score))
    max_ats_enrich = int(defaults.get("max_ats_enrichments", 10))

    boards = get_enabled_boards(config, board_ids=board_ids, phase=phase)
    run_id = _new_run_id()
    summary = BoardDiscoverySummary(run_id=run_id, dry_run=dry_run)
    client = BoardHttpClient(delay_ms=delay_ms)
    all_candidates: list[JobCandidate] = []

    for board in boards:
        stats = BoardRunStats(source_id=board.source_id)
        adapter = get_adapter(board.adapter)
        board_pages = board.max_pages_per_query or max_pages

        board_failed = False
        query_list = search_queries[: discovery_config.budgets.max_search_queries]
        if board.fetch_once and query_list:
            query_list = query_list[:1]

        for query in query_list:
            if board_failed:
                break
            stats.queries_run += 1
            try:
                found = adapter.search(
                    query,
                    location=resolved_location,
                    source=board,
                    client=client,
                    max_pages=board_pages,
                )
            except Exception as exc:
                stats.notes = f"error: {exc}"
                logger.warning("Board %s query %r failed: %s", board.source_id, query, exc)
                if is_persistent_board_error(exc):
                    board_failed = True
                continue
            stats.raw_jobs += len(found)
            all_candidates.extend(found)

        summary.board_stats.append(stats)
        summary.boards_checked += 1

    summary.raw_jobs_found = len(all_candidates)
    deduped = _dedupe_candidates(all_candidates)
    filtered = filter_jobs(
        deduped,
        min_keyword_score=min_keyword_score,
        title_only=discovery_config.prescreen.title_only,
        location_filters=discovery_config.location_filters if defaults.get("require_canada_location", True) else [],
        require_location_match=discovery_config.prescreen.require_location_match,
        location_score_boost=discovery_config.prescreen.location_score_boost,
    )
    summary.jobs_after_filter = len(filtered)

    if enrich_ats and filtered:
        filtered = enrich_ats_job_descriptions(filtered, max_enrichments=max_ats_enrich)

    if dry_run:
        summary.inserted = 0
        _log_run(summary, notes=f"dry_run run_id={run_id} raw={summary.raw_jobs_found} filtered={summary.jobs_after_filter}")
        return summary

    save_result = save_jobs(
        filtered,
        create_company_if_missing=True,
        pending_evaluation=True,
        discovery_run_id=run_id,
    )
    summary.inserted = save_result.inserted
    summary.duplicates_skipped = save_result.duplicates_skipped
    summary.companies_created = save_result.companies_created

    _log_run(
        summary,
        notes=(
            f"run_id={run_id} boards={summary.boards_checked} raw={summary.raw_jobs_found} "
            f"filtered={summary.jobs_after_filter} inserted={summary.inserted} "
            f"companies_created={summary.companies_created}"
        ),
    )
    return summary
