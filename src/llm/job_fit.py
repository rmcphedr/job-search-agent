"""Job fit scoring via local Ollama LLM."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from src.llm.cache import is_cache_enabled, job_cache_key, load_cached_result, save_cached_result
from src.llm.llm_client import LLMClientError, OllamaClient, load_llm_config
from src.llm.prompts import build_job_fit_prompt, parse_company_notes
from src.llm.schemas import JobFitResult

logger = logging.getLogger(__name__)


def score_job(
    job_record: dict[str, object],
    *,
    company_context: dict[str, str] | None = None,
    client: OllamaClient | None = None,
    force_refresh: bool = False,
) -> JobFitResult:
    """Score a single job posting for candidate fit."""
    config = load_llm_config()
    cache_key = job_cache_key(job_record)

    if not force_refresh and is_cache_enabled(config):
        cached = load_cached_result("job_fit", cache_key)
        if cached is not None:
            logger.info(
                "Using cached job fit score for %s at %s",
                job_record.get("title") or job_record.get("job_title"),
                job_record.get("company") or job_record.get("company_name"),
            )
            return JobFitResult.model_validate(cached)

    llm_client = client or OllamaClient(config)
    prompt = build_job_fit_prompt(job_record, company_context=company_context)

    try:
        raw = llm_client.generate_json(prompt)
    except LLMClientError:
        raise

    title = str(job_record.get("title") or job_record.get("job_title") or "").strip()
    company = str(job_record.get("company") or job_record.get("company_name") or "").strip()
    if title and not raw.get("job_title"):
        raw["job_title"] = title
    if company and not raw.get("company_name"):
        raw["company_name"] = company

    try:
        result = JobFitResult.model_validate(raw)
    except ValidationError as exc:
        raise LLMClientError(f"Invalid job fit response: {exc}") from exc

    if is_cache_enabled(config):
        save_cached_result("job_fit", cache_key, result.model_dump())

    return result


def build_company_context_from_inventory_row(row: dict[str, object]) -> dict[str, str]:
    """Build company context fields from an inventory CSV row."""
    notes = parse_company_notes(row.get("notes", ""))
    return {
        "industry": str(row.get("industry", "")).strip(),
        "description": notes.get("description", ""),
    }


def score_job_safe(
    job_record: dict[str, object],
    *,
    company_context: dict[str, str] | None = None,
    client: OllamaClient | None = None,
    force_refresh: bool = False,
) -> tuple[JobFitResult | None, str | None]:
    """Score a job and return (result, error_message)."""
    try:
        return (
            score_job(
                job_record,
                company_context=company_context,
                client=client,
                force_refresh=force_refresh,
            ),
            None,
        )
    except LLMClientError as exc:
        title = job_record.get("title") or job_record.get("job_title") or "unknown"
        logger.error("Failed to score job %s: %s", title, exc)
        return None, str(exc)
