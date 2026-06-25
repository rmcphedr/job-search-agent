"""Load job discovery configuration (budgets, pre-screening, search queries)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from src.database.db import get_project_root
from src.jobs.filter_jobs import load_job_filter_config

DEFAULT_CONFIG_PATH = get_project_root() / "config" / "job_discovery.yaml"

SIZE_TIER_ALIASES: dict[str, str] = {
    "startup": "startup",
    "small": "startup",
    "mid": "mid",
    "medium": "mid",
    "large": "large",
    "enterprise": "large",
    "corporation": "large",
}


@dataclass(frozen=True)
class PrescreenConfig:
    min_keyword_score: float = 0.25
    title_only: bool = True
    format_descriptions: bool = True
    require_location_match: bool = False
    location_score_boost: float = 0.10


@dataclass(frozen=True)
class BudgetConfig:
    max_search_queries: int = 10
    max_listing_pages_per_query: int = 3
    max_listings_per_company: int = 100
    max_detail_fetches: int = 10
    max_jobs_saved_per_company: int = 25
    max_llm_triage_calls: int = 30
    max_llm_fit_scores: int = 5


@dataclass(frozen=True)
class LLMTriageConfig:
    enabled: bool = True
    min_triage_score: float = 6.0
    fallback_to_keywords: bool = True


@dataclass(frozen=True)
class LLMFitConfig:
    enabled: bool = True


@dataclass(frozen=True)
class DiscoveryConfig:
    prescreen: PrescreenConfig
    budgets: BudgetConfig
    llm_triage: LLMTriageConfig
    llm_fit: LLMFitConfig
    search_queries: list[str]
    location_filters: list[str]
    budgets_by_size: dict[str, dict[str, object]]


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


def normalize_size_tier(size: object) -> str:
    """Map inventory size labels to startup, mid, large, or default."""
    text = str(size or "").strip().lower()
    if not text or text in {"unknown", "n/a", "na"}:
        return "default"
    for alias, tier in SIZE_TIER_ALIASES.items():
        if alias in text:
            return tier
    return "default"


def _load_budget_overrides(raw: object) -> dict[str, dict[str, object]]:
    if not isinstance(raw, dict):
        return {}
    overrides: dict[str, dict[str, object]] = {}
    for tier, values in raw.items():
        if isinstance(values, dict):
            overrides[str(tier).strip().lower()] = values
    return overrides


def _apply_size_overrides(
    config: DiscoveryConfig,
    *,
    size_tier: str,
) -> DiscoveryConfig:
    overrides = config.budgets_by_size.get(size_tier) or config.budgets_by_size.get("default")
    if not overrides:
        return config

    prescreen = config.prescreen
    if "min_keyword_score" in overrides:
        prescreen = replace(
            prescreen,
            min_keyword_score=_coerce_float(
                overrides["min_keyword_score"],
                prescreen.min_keyword_score,
            ),
        )

    budgets = config.budgets
    budget_fields = {
        "max_search_queries": budgets.max_search_queries,
        "max_listing_pages_per_query": budgets.max_listing_pages_per_query,
        "max_listings_per_company": budgets.max_listings_per_company,
        "max_detail_fetches": budgets.max_detail_fetches,
        "max_jobs_saved_per_company": budgets.max_jobs_saved_per_company,
        "max_llm_triage_calls": budgets.max_llm_triage_calls,
        "max_llm_fit_scores": budgets.max_llm_fit_scores,
    }
    updated_budgets: dict[str, int] = {}
    for field, default in budget_fields.items():
        if field in overrides:
            updated_budgets[field] = _coerce_int(overrides[field], default)
    if updated_budgets:
        budgets = replace(budgets, **updated_budgets)

    search_queries = config.search_queries
    if "max_search_queries" in updated_budgets:
        search_queries = search_queries[: updated_budgets["max_search_queries"]]

    return replace(
        config,
        prescreen=prescreen,
        budgets=budgets,
        search_queries=search_queries,
    )


def resolve_discovery_config_for_company(
    config: DiscoveryConfig,
    *,
    company_size: object = None,
    company_name: str | None = None,
) -> DiscoveryConfig:
    """Apply company-size budget overrides for a single discovery run."""
    tier = normalize_size_tier(company_size)
    if tier == "default" and company_name:
        name = company_name.lower()
        if any(token in name for token in ("corporation", "inc.", " inc", "pharma", "global")):
            tier = "large"
    return _apply_size_overrides(config, size_tier=tier)


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
    llm_triage_raw = data.get("llm_triage", {})
    llm_fit_raw = data.get("llm_fit", {})
    if not isinstance(prescreen_raw, dict):
        prescreen_raw = {}
    if not isinstance(budgets_raw, dict):
        budgets_raw = {}
    if not isinstance(llm_triage_raw, dict):
        llm_triage_raw = {}
    if not isinstance(llm_fit_raw, dict):
        llm_fit_raw = {}

    filter_config = load_job_filter_config()

    prescreen = PrescreenConfig(
        min_keyword_score=_coerce_float(prescreen_raw.get("min_keyword_score"), 0.25),
        title_only=_coerce_bool(prescreen_raw.get("title_only"), True),
        format_descriptions=_coerce_bool(prescreen_raw.get("format_descriptions"), True),
        require_location_match=_coerce_bool(prescreen_raw.get("require_location_match"), False),
        location_score_boost=_coerce_float(prescreen_raw.get("location_score_boost"), 0.10),
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
        max_llm_triage_calls=_coerce_int(budgets_raw.get("max_llm_triage_calls"), 30),
        max_llm_fit_scores=_coerce_int(budgets_raw.get("max_llm_fit_scores"), 5),
    )
    llm_triage = LLMTriageConfig(
        enabled=_coerce_bool(llm_triage_raw.get("enabled"), True),
        min_triage_score=_coerce_float(llm_triage_raw.get("min_triage_score"), 6.0),
        fallback_to_keywords=_coerce_bool(
            llm_triage_raw.get("fallback_to_keywords"), True
        ),
    )
    llm_fit = LLMFitConfig(
        enabled=_coerce_bool(llm_fit_raw.get("enabled"), True),
    )

    search_queries = list(filter_config.get("search_queries", []))
    configured_queries = data.get("search_queries", [])
    if isinstance(configured_queries, list):
        override_queries = [str(item).strip() for item in configured_queries if str(item).strip()]
        if override_queries:
            search_queries = override_queries

    if not search_queries:
        search_queries = list(filter_config.get("high_value_roles", []))

    return DiscoveryConfig(
        prescreen=prescreen,
        budgets=budgets,
        llm_triage=llm_triage,
        llm_fit=llm_fit,
        search_queries=search_queries,
        location_filters=list(filter_config.get("location_filters", [])),
        budgets_by_size=_load_budget_overrides(data.get("budgets_by_size")),
    )
