"""Apply full LLM fit scores during job discovery."""

from __future__ import annotations

import logging

from src.jobs.job_models import JobCandidate
from src.llm.job_fit import score_job_safe
from src.llm.llm_client import OllamaClient

logger = logging.getLogger(__name__)


def _job_to_record(job: JobCandidate) -> dict[str, object]:
    return {
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "description": job.description,
    }


def apply_llm_fit_scores(
    jobs: list[JobCandidate],
    *,
    company_context: dict[str, str],
    enabled: bool = True,
    max_scores: int = 5,
    client: OllamaClient | None = None,
) -> tuple[list[JobCandidate], int]:
    """Score up to max_scores jobs with the full-fit LLM prompt."""
    if not enabled or max_scores <= 0 or not jobs:
        return jobs, 0

    updated: list[JobCandidate] = []
    scored = 0

    for job in jobs[:max_scores]:
        result, error = score_job_safe(
            _job_to_record(job),
            company_context=company_context,
            client=client,
        )
        if result is None:
            logger.warning("LLM fit scoring skipped for %s: %s", job.title, error)
            updated.append(job)
            continue

        notes = job.notes or ""
        fit_note = f"llm_fit={result.fit_score:.1f}: {result.why_fit[:160]}"
        combined_notes = f"{notes}; {fit_note}" if notes else fit_note
        updated.append(
            job.model_copy(
                update={
                    "llm_fit_score": result.fit_score,
                    "fit_details": result.model_dump_json(),
                    "notes": combined_notes,
                }
            )
        )
        scored += 1

    updated.extend(jobs[max_scores:])
    return updated, scored
