"""Unit tests for company-size-aware discovery configuration."""

from src.jobs.discovery_config import (
    load_discovery_config,
    normalize_size_tier,
    resolve_discovery_config_for_company,
)
from src.jobs.filter_jobs import load_job_filter_config, matches_location_filter


def test_search_queries_loaded_from_job_keywords() -> None:
    filter_config = load_job_filter_config()
    config = load_discovery_config()
    assert filter_config["search_queries"]
    assert config.search_queries
    assert "machine learning" in config.search_queries


def test_location_filters_loaded() -> None:
    config = load_discovery_config()
    assert "canada" in config.location_filters
    assert matches_location_filter("San Diego, CA", config.location_filters) is False
    assert matches_location_filter("Vancouver, BC", config.location_filters) is True
    assert matches_location_filter("Remote", config.location_filters) is True


def test_size_tier_normalization() -> None:
    assert normalize_size_tier("Startup") == "startup"
    assert normalize_size_tier("Medium") == "mid"
    assert normalize_size_tier("") == "default"


def test_large_company_budget_overrides() -> None:
    base = load_discovery_config()
    resolved = resolve_discovery_config_for_company(
        base,
        company_size="",
        company_name="AbbVie Corporation",
    )
    assert resolved.prescreen.min_keyword_score >= 0.35
    assert resolved.budgets.max_detail_fetches <= 10
    assert resolved.budgets.max_llm_triage_calls >= 30
    assert resolved.llm_triage.enabled is True


def test_startup_budget_overrides() -> None:
    base = load_discovery_config()
    resolved = resolve_discovery_config_for_company(base, company_size="Startup")
    assert resolved.prescreen.min_keyword_score <= 0.20
    assert resolved.budgets.max_detail_fetches >= 20
