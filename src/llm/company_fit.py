"""Company fit scoring via local Ollama LLM."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from src.llm.cache import company_cache_key, is_cache_enabled, load_cached_result, save_cached_result
from src.llm.llm_client import LLMClientError, OllamaClient, load_llm_config
from src.llm.prompts import build_company_fit_prompt
from src.llm.schemas import CompanyFitResult

logger = logging.getLogger(__name__)


def score_company(
    company_record: dict[str, object],
    *,
    client: OllamaClient | None = None,
    force_refresh: bool = False,
) -> CompanyFitResult:
    """Score a single company for candidate fit."""
    config = load_llm_config()
    cache_key = company_cache_key(company_record)

    if not force_refresh and is_cache_enabled(config):
        cached = load_cached_result("company_fit", cache_key)
        if cached is not None:
            logger.info(
                "Using cached company fit score for %s",
                company_record.get("company_name", "unknown"),
            )
            return CompanyFitResult.model_validate(cached)

    llm_client = client or OllamaClient(config)
    prompt = build_company_fit_prompt(company_record)

    try:
        raw = llm_client.generate_json(prompt)
    except LLMClientError:
        raise

    expected_name = str(company_record.get("company_name", "")).strip()
    if expected_name and not raw.get("company_name"):
        raw["company_name"] = expected_name

    try:
        result = CompanyFitResult.model_validate(raw)
    except ValidationError as exc:
        raise LLMClientError(f"Invalid company fit response: {exc}") from exc

    if is_cache_enabled(config):
        save_cached_result("company_fit", cache_key, result.model_dump())

    return result


def score_company_safe(
    company_record: dict[str, object],
    *,
    client: OllamaClient | None = None,
    force_refresh: bool = False,
) -> tuple[CompanyFitResult | None, str | None]:
    """Score a company and return (result, error_message)."""
    try:
        return score_company(company_record, client=client, force_refresh=force_refresh), None
    except LLMClientError as exc:
        name = company_record.get("company_name", "unknown")
        logger.error("Failed to score company %s: %s", name, exc)
        return None, str(exc)
