"""Sandbox probe for Playwright board adapters — verify fetch + parse without DB writes."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field

from src.jobs.board_discovery.config import get_enabled_boards, load_board_sources_config
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.playwright_client import PlaywrightBrowserClient, playwright_available
from src.jobs.board_discovery.registry import get_adapter

logger = logging.getLogger(__name__)

DEFAULT_QUERY = "machine learning"
DEFAULT_LOCATION = "Canada"


@dataclass
class BoardProbeResult:
    source_id: str
    adapter: str
    scrape_mode: str
    status: str
    jobs_found: int = 0
    blocked_reason: str | None = None
    error: str | None = None
    sample_titles: list[str] = field(default_factory=list)
    final_url: str | None = None
    html_bytes: int = 0


def probe_playwright_board(
    *,
    source_id: str,
    query: str = DEFAULT_QUERY,
    location: str = DEFAULT_LOCATION,
    max_pages: int = 1,
) -> BoardProbeResult:
    config = load_board_sources_config()
    boards = {board.source_id: board for board in config.boards}
    board = boards.get(source_id)
    if board is None:
        return BoardProbeResult(
            source_id=source_id,
            adapter="",
            scrape_mode="",
            status="missing",
            error=f"Unknown board: {source_id}",
        )
    if board.scrape_mode != "playwright":
        return BoardProbeResult(
            source_id=source_id,
            adapter=board.adapter,
            scrape_mode=board.scrape_mode,
            status="skipped",
            error="Board is not configured for Playwright",
        )
    if not playwright_available():
        return BoardProbeResult(
            source_id=source_id,
            adapter=board.adapter,
            scrape_mode=board.scrape_mode,
            status="error",
            error="Playwright not installed",
        )

    adapter = get_adapter(board.adapter, scrape_mode=board.scrape_mode)
    client = BoardHttpClient(delay_ms=0)
    found: list = []
    blocked_reason = None
    html_bytes = 0
    final_url = None

    try:
        with PlaywrightBrowserClient(delay_ms=500) as browser:
            found = adapter.search(
                query,
                location=location,
                source=board,
                client=client,
                max_pages=max_pages,
                browser=browser,
            )
            if browser_cache := getattr(browser, "_html_cache", {}):
                first = next(iter(browser_cache.values()), None)
                if first is not None:
                    blocked_reason = first.blocked_reason
                    html_bytes = len(first.html)
                    final_url = first.final_url
    except Exception as exc:
        return BoardProbeResult(
            source_id=source_id,
            adapter=board.adapter,
            scrape_mode=board.scrape_mode,
            status="error",
            error=str(exc),
        )

    status = "ok"
    if blocked_reason:
        status = "blocked"
    elif not found:
        status = "empty"

    return BoardProbeResult(
        source_id=source_id,
        adapter=board.adapter,
        scrape_mode=board.scrape_mode,
        status=status,
        jobs_found=len(found),
        blocked_reason=blocked_reason,
        sample_titles=[job.title for job in found[:3]],
        final_url=final_url,
        html_bytes=html_bytes,
    )


def probe_all_playwright_boards(
    *,
    query: str = DEFAULT_QUERY,
    location: str = DEFAULT_LOCATION,
    max_pages: int = 1,
    phase: int | None = 3,
) -> list[BoardProbeResult]:
    config = load_board_sources_config()
    boards = get_enabled_boards(config, phase=phase)
    playwright_boards = [board for board in boards if board.scrape_mode == "playwright"]
    return [
        probe_playwright_board(
            source_id=board.source_id,
            query=query,
            location=location,
            max_pages=max_pages,
        )
        for board in playwright_boards
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe Playwright job boards in sandbox mode (no database writes).",
    )
    parser.add_argument(
        "--boards",
        type=str,
        default="",
        help="Comma-separated source_id list (default: all enabled Playwright boards).",
    )
    parser.add_argument("--query", type=str, default=DEFAULT_QUERY, help="Search query.")
    parser.add_argument("--location", type=str, default=DEFAULT_LOCATION, help="Location filter.")
    parser.add_argument("--max-pages", type=int, default=1, help="Pages per board.")
    parser.add_argument("--phase", type=int, default=3, help="Max board phase to include.")
    parser.add_argument("--json", action="store_true", help="Emit JSON results.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    board_ids = [item.strip() for item in args.boards.split(",") if item.strip()] or None
    if board_ids:
        results = [
            probe_playwright_board(
                source_id=board_id,
                query=args.query,
                location=args.location,
                max_pages=args.max_pages,
            )
            for board_id in board_ids
        ]
    else:
        results = probe_all_playwright_boards(
            query=args.query,
            location=args.location,
            max_pages=args.max_pages,
            phase=args.phase,
        )

    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        ok = sum(1 for result in results if result.status == "ok" and result.jobs_found > 0)
        blocked = sum(1 for result in results if result.status == "blocked")
        empty = sum(1 for result in results if result.status == "empty")
        errors = sum(1 for result in results if result.status == "error")
        print(f"Playwright sandbox: {len(results)} boards | ok={ok} blocked={blocked} empty={empty} errors={errors}")
        for result in results:
            line = f"  {result.source_id}: {result.status}"
            if result.jobs_found:
                line += f" jobs={result.jobs_found}"
            if result.blocked_reason:
                line += f" blocked={result.blocked_reason}"
            if result.error:
                line += f" error={result.error[:120]}"
            if result.sample_titles:
                line += f" sample={result.sample_titles[0]!r}"
            print(line)

    has_hard_failure = any(result.status in {"error", "missing"} for result in results)
    has_success = any(result.jobs_found > 0 for result in results)
    return 0 if has_success or not has_hard_failure else 1


if __name__ == "__main__":
    raise SystemExit(main())
