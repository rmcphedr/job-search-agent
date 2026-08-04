"""Configuration models for job board discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.database.db import get_project_root

DEFAULT_CONFIG_PATH = get_project_root() / "config" / "job_board_sources.yaml"


@dataclass(frozen=True)
class BoardSource:
    source_id: str
    name: str
    adapter: str
    priority: str = "medium"
    phase: int = 1
    enabled: bool = True
    base_url: str = ""
    search_path: str | None = None
    search_params: dict[str, str] = field(default_factory=dict)
    search_url_template: str | None = None
    selectors: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    max_pages_per_query: int | None = None
    fetch_once: bool = False
    scrape_mode: str = "requests"
    wait_selector: str | None = None


@dataclass(frozen=True)
class BoardSourcesConfig:
    defaults: dict[str, Any]
    job_board_domains: list[str]
    boards: list[BoardSource]
    ats_providers: list[str]


def _parse_board(raw: dict[str, Any]) -> BoardSource:
    selectors = raw.get("selectors", {})
    if not isinstance(selectors, dict):
        selectors = {}
    search_params = raw.get("search_params", {})
    if not isinstance(search_params, dict):
        search_params = {}

    return BoardSource(
        source_id=str(raw["source_id"]),
        name=str(raw.get("name", raw["source_id"])),
        adapter=str(raw.get("adapter", "stub")),
        priority=str(raw.get("priority", "medium")),
        phase=int(raw.get("phase", 1)),
        enabled=bool(raw.get("enabled", True)),
        base_url=str(raw.get("base_url", "")),
        search_path=raw.get("search_path"),
        search_params={str(k): str(v) for k, v in search_params.items()},
        search_url_template=raw.get("search_url_template"),
        selectors={str(k): str(v) for k, v in selectors.items()},
        notes=str(raw.get("notes", "")),
        max_pages_per_query=raw.get("max_pages_per_query"),
        fetch_once=bool(raw.get("fetch_once", False)),
        scrape_mode=str(raw.get("scrape_mode", "requests")),
        wait_selector=raw.get("wait_selector"),
    )


def load_board_sources_config(config_path: Path | None = None) -> BoardSourcesConfig:
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Job board config not found: {path}")

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise RuntimeError(f"Job board config must be a mapping: {path}")

    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        defaults = {}

    domains = data.get("job_board_domains", [])
    if not isinstance(domains, list):
        domains = []

    boards_raw = data.get("boards", [])
    if not isinstance(boards_raw, list):
        raise RuntimeError(f"'boards' must be a list in {path}")

    boards = [_parse_board(item) for item in boards_raw if isinstance(item, dict)]

    ats_providers = data.get("ats_providers", [])
    if not isinstance(ats_providers, list):
        ats_providers = []

    return BoardSourcesConfig(
        defaults=defaults,
        job_board_domains=[str(domain) for domain in domains],
        boards=boards,
        ats_providers=[str(provider) for provider in ats_providers],
    )


def boards_need_playwright(boards: list[BoardSource]) -> bool:
    return any(board.scrape_mode == "playwright" for board in boards)


def get_enabled_boards(
    config: BoardSourcesConfig,
    *,
    board_ids: list[str] | None = None,
    phase: int | None = None,
) -> list[BoardSource]:
    boards = [board for board in config.boards if board.enabled]
    if board_ids:
        allowed = {board_id.strip().lower() for board_id in board_ids}
        boards = [board for board in boards if board.source_id.lower() in allowed]
    if phase is not None:
        boards = [board for board in boards if board.phase <= phase]
    return boards
