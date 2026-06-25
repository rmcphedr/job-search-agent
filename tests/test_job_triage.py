"""Unit tests for LLM job triage helpers."""

from __future__ import annotations

from unittest.mock import patch

from src.jobs.job_models import JobCandidate
from src.llm.cache import job_triage_cache_key
from src.llm.job_triage import passes_triage, triage_jobs
from src.llm.schemas import JobTriageResult


def _sample_job(title: str = "Machine Learning Scientist") -> JobCandidate:
    return JobCandidate(
        company_name="AbbVie",
        title=title,
        location="San Diego, CA",
        source_career_page="https://careers.abbvie.com",
        keyword_score=0.8,
        matched_keywords=["machine learning"],
    )


def test_job_triage_cache_key_uses_title_not_description() -> None:
    base = {
        "title": "Data Scientist",
        "company_name": "AbbVie",
        "location": "Remote",
        "keyword_score": 0.5,
        "matched_keywords": ["data scientist"],
    }
    with_description = {**base, "description": "Long description should not matter"}
    assert job_triage_cache_key(base) == job_triage_cache_key(with_description)


def test_passes_triage_threshold() -> None:
    high = JobTriageResult(
        job_title="ML Scientist",
        company_name="AbbVie",
        worth_reviewing=False,
        triage_score=7.5,
        reason="Strong title match",
        confidence=8.0,
    )
    low = JobTriageResult(
        job_title="Sales Rep",
        company_name="AbbVie",
        worth_reviewing=False,
        triage_score=3.0,
        reason="Sales role",
        confidence=8.0,
    )
    flagged = JobTriageResult(
        job_title="Associate",
        company_name="AbbVie",
        worth_reviewing=True,
        triage_score=4.0,
        reason="Ambiguous but flagged",
        confidence=5.0,
    )
    assert passes_triage(high, min_triage_score=6.0) is True
    assert passes_triage(low, min_triage_score=6.0) is False
    assert passes_triage(flagged, min_triage_score=6.0) is True


def test_triage_jobs_disabled_passes_all() -> None:
    jobs = [_sample_job("Data Scientist"), _sample_job("Research Scientist")]
    triaged, count = triage_jobs(jobs, enabled=False)
    assert triaged == jobs
    assert count == 2


@patch("src.llm.job_triage.triage_job_safe")
def test_triage_jobs_filters_low_scores(mock_triage) -> None:
    mock_triage.side_effect = [
        (
            JobTriageResult(
                job_title="Machine Learning Scientist",
                company_name="AbbVie",
                worth_reviewing=True,
                triage_score=8.0,
                reason="Strong match",
                confidence=9.0,
            ),
            None,
        ),
        (
            JobTriageResult(
                job_title="Sales Representative",
                company_name="AbbVie",
                worth_reviewing=False,
                triage_score=2.0,
                reason="Sales role",
                confidence=9.0,
            ),
            None,
        ),
    ]
    jobs = [_sample_job("Machine Learning Scientist"), _sample_job("Sales Representative")]
    triaged, count = triage_jobs(jobs, enabled=True, min_triage_score=6.0, max_calls=5)
    assert count == 1
    assert len(triaged) == 1
    assert triaged[0].title == "Machine Learning Scientist"
    assert triaged[0].triage_score == 8.0


@patch("src.llm.job_triage.triage_job_safe")
def test_triage_jobs_fallback_on_llm_error(mock_triage) -> None:
    mock_triage.return_value = (None, "connection refused")
    jobs = [_sample_job()]
    triaged, count = triage_jobs(
        jobs,
        enabled=True,
        fallback_to_keywords=True,
        max_calls=5,
    )
    assert count == 1
    assert len(triaged) == 1
