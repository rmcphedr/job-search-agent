"""LLM-based cleaning and structuring of scraped job descriptions."""

from __future__ import annotations

import hashlib
import logging
import re

from src.jobs.job_url_utils import normalize_text
from src.database.db import get_project_root
from src.llm.cache import is_cache_enabled, load_cached_result, save_cached_result
from src.llm.llm_client import LLMClientError, OllamaClient, load_llm_config
from src.llm.prompts import _load_template

logger = logging.getLogger(__name__)

JOB_DESCRIPTION_TEMPLATE_PATH = get_project_root() / "prompts" / "job_description_format.md"

MIN_RAW_DESCRIPTION_CHARS = 80


def _description_cache_key(
    *,
    company_name: str,
    title: str,
    location: str | None,
    location_type: str | None,
    raw_description: str,
) -> str:
    payload = "|".join(
        [
            normalize_text(company_name),
            normalize_text(title),
            normalize_text(location or ""),
            normalize_text(location_type or ""),
            normalize_text(raw_description)[:4000],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


SECTION_HEADERS = (
    "Location:",
    "Work Location Type:",
    "Job Description:",
    "Qualifications:",
    "Preferred Qualifications:",
    "Benefits:",
)


def _normalize_formatted_description(text: str) -> str:
    normalized = text.strip()
    for header in SECTION_HEADERS:
        normalized = re.sub(
            rf"\s*(?<!\n)({re.escape(header)})",
            rf"\n\n\1",
            normalized,
        )
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _basic_clean_description(raw_description: str) -> str:
    text = raw_description
    text = re.sub(r"__[\w.]+__", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fallback_formatted_description(
    *,
    location: str | None,
    location_type: str | None,
    raw_description: str,
) -> str:
    sections: list[str] = []
    if location:
        sections.append(f"Location: {location}")
    if location_type:
        sections.append(f"Work Location Type: {location_type}")
    cleaned = _basic_clean_description(raw_description)
    if cleaned:
        sections.append(f"Job Description:\n{cleaned}")
    return _normalize_formatted_description("\n\n".join(sections))


def format_job_description(
    *,
    company_name: str,
    title: str,
    location: str | None,
    location_type: str | None,
    raw_description: str | None,
    client: OllamaClient | None = None,
    force_refresh: bool = False,
) -> str | None:
    """Return a cleaned structured description, using LLM when available."""
    if not raw_description or len(raw_description.strip()) < MIN_RAW_DESCRIPTION_CHARS:
        return None

    config = load_llm_config()
    cache_key = _description_cache_key(
        company_name=company_name,
        title=title,
        location=location,
        location_type=location_type,
        raw_description=raw_description,
    )

    if not force_refresh and is_cache_enabled(config):
        cached = load_cached_result("job_description", cache_key)
        if cached and isinstance(cached.get("formatted_description"), str):
            return _normalize_formatted_description(cached["formatted_description"])

    template = _load_template(JOB_DESCRIPTION_TEMPLATE_PATH)
    prompt = template.format(
        company_name=company_name or "Unknown",
        job_title=title or "Unknown",
        location=location or "Not provided",
        location_type=location_type or "Not provided",
        raw_description=raw_description[:12000],
    )

    try:
        llm_client = client or OllamaClient(config)
        payload = llm_client.generate_json(prompt)
        formatted = payload.get("formatted_description")
        if isinstance(formatted, str) and formatted.strip():
            result = _normalize_formatted_description(formatted.strip())
            if is_cache_enabled(config):
                save_cached_result(
                    "job_description",
                    cache_key,
                    {"formatted_description": result},
                )
            return result
    except LLMClientError as exc:
        logger.warning("LLM description formatting failed for %s: %s", title, exc)

    return _fallback_formatted_description(
        location=location,
        location_type=location_type,
        raw_description=raw_description,
    )


def format_job_description_safe(
    *,
    company_name: str,
    title: str,
    location: str | None,
    location_type: str | None,
    raw_description: str | None,
    client: OllamaClient | None = None,
    force_refresh: bool = False,
) -> tuple[str | None, str | None]:
    """Format a job description and return (result, error_message)."""
    try:
        return (
            format_job_description(
                company_name=company_name,
                title=title,
                location=location,
                location_type=location_type,
                raw_description=raw_description,
                client=client,
                force_refresh=force_refresh,
            ),
            None,
        )
    except LLMClientError as exc:
        return (
            _fallback_formatted_description(
                location=location,
                location_type=location_type,
                raw_description=raw_description or "",
            ),
            str(exc),
        )
