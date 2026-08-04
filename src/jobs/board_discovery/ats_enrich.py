"""Enrich board-discovered jobs from ATS-hosted detail pages."""

from __future__ import annotations

import logging

from src.jobs.job_extractors import extract_job_detail
from src.jobs.job_models import JobCandidate
from src.jobs.job_url_utils import detect_provider_from_url

logger = logging.getLogger(__name__)

ATS_PROVIDERS = frozenset(
    {
        "greenhouse",
        "lever",
        "ashby",
        "workday",
        "smartrecruiters",
        "icims",
    }
)


def enrich_ats_job_descriptions(
    candidates: list[JobCandidate],
    *,
    max_enrichments: int = 10,
) -> list[JobCandidate]:
    """Fetch descriptions for jobs hosted on supported ATS platforms."""
    enriched: list[JobCandidate] = []
    enrichments = 0

    for candidate in candidates:
        if enrichments >= max_enrichments:
            enriched.append(candidate)
            continue

        url = candidate.url or ""
        provider = detect_provider_from_url(url)
        if provider not in ATS_PROVIDERS:
            enriched.append(candidate)
            continue
        if candidate.description and len(candidate.description) > 200:
            enriched.append(candidate)
            continue

        try:
            detail = extract_job_detail(url, company_name=candidate.company_name, format_description=False)
        except Exception as exc:
            logger.debug("ATS enrich failed for %s: %s", url, exc)
            enriched.append(candidate)
            continue

        enrichments += 1
        updates: dict[str, object] = {"provider": provider}
        if detail.get("description"):
            updates["description"] = detail["description"]
        if detail.get("location") and not candidate.location:
            updates["location"] = detail["location"]
        if detail.get("title") and detail["title"]:
            updates["title"] = detail["title"]
        if detail.get("url"):
            updates["url"] = detail["url"]

        enriched.append(candidate.model_copy(update=updates))

    return enriched
