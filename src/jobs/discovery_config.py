"""Load job discovery configuration (budgets, pre-screening, search queries)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from src.database.db import get_project_root
from src.jobs.filter_jobs import load_job_keywords

DEFAULT_CONFIG_PATH = get_project_root() / "config" / "job_discovery.yaml"


@dataclass(frozen=True)
class PrescreenConfig:
    min_keyword_score: float = 0.25
    title_only: bool = True
    format_descriptions: bool = True


@dataclass(frozen=True)
class BudgetConfig:
    max_search_queries: int = 10
    max_listing_pages_per_query: int = 3
    max_listings_per_company: int = 100
    max_detail_fetches: int = 10
    max_jobs_saved_per_company: int = 25


@dataclass(frozen=True)
class DiscoveryConfig:
    prescreen: PrescreenConfig
    budgets: BudgetConfig
    search_queries: list[str]


def _coerce_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def load_discovery_config(config_path: Path | None = None) -> DiscoveryConfig:
    """Load discovery settings from YAML, falling back to sensible defaults."""
    path = config_path or DEFAULT_CONFIG_PATH
    data: dict[str, object] = {}
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        if isinstance(loaded, dict):
            data = loaded

    prescreen_raw = data.get("prescreen", {})
    budgets_raw = data.get("budgets", {})
    if not isinstance(prescreen_raw, dict):
        prescreen_raw = {}
    if not isinstance(budgets_raw, dict):
        budgets_raw = {}

    prescreen = PrescreenConfig(
        min_keyword_score=_coerce_float(prescreen_raw.get("min_keyword_score"), 0.25),
        title_only=_coerce_bool(prescreen_raw.get("title_only"), True),
        format_descriptions=_coerce_bool(prescreen_raw.get("format_descriptions"), True),
    )
    budgets = BudgetConfig(
        max_search_queries=_coerce_int(budgets_raw.get("max_search_queries"), 10),
        max_listing_pages_per_query=_coerce_int(
            budgets_raw.get("max_listing_pages_per_query"), 3
        ),
        max_listings_per_company=_coerce_int(
            budgets_raw.get("max_listings_per_company"), 100
        ),
        max_detail_fetches=_coerce_int(budgets_raw.get("max_detail_fetches"), 10),
        max_jobs_saved_per_company=_coerce_int(
            budgets_raw.get("max_jobs_saved_per_company"), 25
        ),
    )

    search_queries: list[str] = []
    configured = data.get("search_queries", [])
    if isinstance(configured, list):
        search_queries = [str(item).strip() for item in configured if str(item).strip()]

    if not search_queries:
        keywords = load_job_keywords()
        search_queries = list(keywords.get("high_value_roles", []))

    return DiscoveryConfig(
        prescreen=prescreen,
        budgets=budgets,
        search_queries=search_queries,
    )
