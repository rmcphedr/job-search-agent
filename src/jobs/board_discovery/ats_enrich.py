"""Enrich board-discovered jobs from authoritative detail pages."""

from __future__ import annotations

import logging
from typing import Any

from src.jobs.description_enrichment import enrich_description
from src.jobs.job_models import JobCandidate

logger = logging.getLogger(__name__)

def enrich_ats_job_descriptions(
    candidates: list[JobCandidate],
    *,
    max_enrichments: int = 10,
    browser: Any | None = None,
) -> list[JobCandidate]:
    """Fetch missing descriptions, using a supplied browser for rendered leads."""
    enriched: list[JobCandidate] = []
    enrichments = 0

    for candidate in candidates:
        if enrichments >= max_enrichments:
            enriched.append(candidate)
            continue

        if candidate.description and len(candidate.description) > 200:
            enriched.append(candidate)
            continue

        try:
            result = enrich_description(candidate.model_dump(), browser=browser)
        except Exception as exc:
            logger.debug("Description enrichment failed for %s: %s", candidate.url, exc)
            enriched.append(candidate)
            continue

        enrichments += 1
        if result.status == "expired":
            continue

        updates: dict[str, object] = {}
        if result.description:
            updates["description"] = result.description
        if result.location and not candidate.location:
            updates["location"] = result.location
        if result.source_url and result.status == "enriched":
            updates["url"] = result.source_url

        enriched.append(candidate.model_copy(update=updates))

    return enriched
