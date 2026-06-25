"""Fast title-only job triage via local Ollama LLM."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from src.jobs.job_models import JobCandidate
from src.llm.cache import (
    is_cache_enabled,
    job_triage_cache_key,
    load_cached_result,
    save_cached_result,
)
from src.llm.llm_client import LLMClientError, OllamaClient, load_llm_config
from src.llm.prompts import build_job_triage_prompt
from src.llm.schemas import JobTriageResult

logger = logging.getLogger(__name__)


def _job_to_record(job: JobCandidate) -> dict[str, object]:
    return {
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "keyword_score": job.keyword_score,
        "matched_keywords": job.matched_keywords,
    }


def passes_triage(result: JobTriageResult, *, min_triage_score: float) -> bool:
    """Return True when a triage result clears the configured threshold."""
    return result.worth_reviewing or result.triage_score >= min_triage_score


def triage_job(
    job_record: dict[str, object],
    *,
    client: OllamaClient | None = None,
    force_refresh: bool = False,
) -> JobTriageResult:
    """Triage a single job from title and metadata only."""
    config = load_llm_config()
    cache_key = job_triage_cache_key(job_record)

    if not force_refresh and is_cache_enabled(config):
        cached = load_cached_result("job_triage", cache_key)
        if cached is not None:
            logger.info(
                "Using cached job triage for %s at %s",
                job_record.get("title") or job_record.get("job_title"),
                job_record.get("company") or job_record.get("company_name"),
            )
            return JobTriageResult.model_validate(cached)

    llm_client = client or OllamaClient(config)
    prompt = build_job_triage_prompt(job_record)

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
        result = JobTriageResult.model_validate(raw)
    except ValidationError as exc:
        raise LLMClientError(f"Invalid job triage response: {exc}") from exc

    if is_cache_enabled(config):
        save_cached_result("job_triage", cache_key, result.model_dump())

    return result


def triage_job_safe(
    job_record: dict[str, object],
    *,
    client: OllamaClient | None = None,
    force_refresh: bool = False,
) -> tuple[JobTriageResult | None, str | None]:
    """Triage a job and return (result, error_message)."""
    try:
        return (
            triage_job(job_record, client=client, force_refresh=force_refresh),
            None,
        )
    except LLMClientError as exc:
        title = job_record.get("title") or job_record.get("job_title") or "unknown"
        logger.error("Failed to triage job %s: %s", title, exc)
        return None, str(exc)


def triage_jobs(
    jobs: list[JobCandidate],
    *,
    enabled: bool = True,
    min_triage_score: float = 6.0,
    max_calls: int = 30,
    fallback_to_keywords: bool = True,
    client: OllamaClient | None = None,
) -> tuple[list[JobCandidate], int]:
    """
    Run LLM triage on the top candidates by keyword score.

    Returns (triaged_jobs, triaged_count) where triaged_count is the number
    that passed the triage gate (including keyword fallback survivors).
    """
    if not jobs:
        return [], 0
    if not enabled:
        return jobs, len(jobs)

    triaged: list[JobCandidate] = []
    llm_calls = 0

    for index, job in enumerate(jobs):
        if llm_calls >= max_calls:
            if fallback_to_keywords:
                triaged.extend(jobs[index:])
            break

        result, _error = triage_job_safe(_job_to_record(job), client=client)
        llm_calls += 1
        if result is None:
            if fallback_to_keywords:
                triaged.append(job)
            continue

        if passes_triage(result, min_triage_score=min_triage_score):
            triaged.append(
                job.model_copy(
                    update={
                        "triage_score": result.triage_score,
                        "notes": result.reason,
                    }
                )
            )

    return triaged, len(triaged)
