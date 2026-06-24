"""Unit tests for search-first job discovery."""

from src.jobs.discovery_config import load_discovery_config
from src.jobs.filter_jobs import prescreen_jobs, score_job
from src.jobs.job_models import JobCandidate
from src.jobs.search_strategies import (
    build_abbvie_search_url,
    build_search_targets,
    dedupe_job_candidates,
    detect_search_strategy,
    job_dedupe_key,
)


def test_detect_abbvie_portal() -> None:
    assert (
        detect_search_strategy(
            "https://careers.abbvie.com/en",
            "<a href='/en/jobs?q=science'>Jobs</a>",
            "generic_html",
        )
        == "abbvie_portal"
    )


def test_build_abbvie_search_url() -> None:
    url = build_abbvie_search_url("https://careers.abbvie.com/en/jobs", "machine learning", 2)
    assert url == "https://careers.abbvie.com/en/jobs?q=machine+learning&page=2"


def test_build_search_targets_for_abbvie() -> None:
    config = load_discovery_config()
    targets = build_search_targets(
        "https://careers.abbvie.com/en",
        "",
        "generic_html",
        config,
    )
    assert len(targets) == 1
    assert targets[0].url.endswith("/en/jobs")


def test_dedupe_by_jid_prefers_clean_title() -> None:
    jobs = [
        JobCandidate(
            company_name="AbbVie",
            title="lead machine learning engineer in san diego ca jid 28673",
            url="https://careers.abbvie.com/en/job/example-jid-28673",
            source_career_page="https://careers.abbvie.com/en",
        ),
        JobCandidate(
            company_name="AbbVie",
            title="Lead Machine Learning Engineer",
            url="https://careers.abbvie.com/en/job/example-jid-28673",
            source_career_page="https://careers.abbvie.com/en",
        ),
    ]
    deduped = dedupe_job_candidates(jobs)
    assert len(deduped) == 1
    assert deduped[0].title == "Lead Machine Learning Engineer"
    assert job_dedupe_key(deduped[0]) == "jid:28673"


def test_prescreen_title_only() -> None:
    relevant = JobCandidate(
        company_name="Test Co",
        title="Senior Machine Learning Engineer",
        source_career_page="https://example.com/careers",
    )
    irrelevant = JobCandidate(
        company_name="Test Co",
        title="Sales Representative",
        source_career_page="https://example.com/careers",
    )
    screened = prescreen_jobs(
        [relevant, irrelevant],
        min_keyword_score=0.25,
        title_only=True,
    )
    assert len(screened) == 1
    assert screened[0].title.startswith("Senior Machine Learning")
    score, _ = score_job(relevant, title_only=True)
    assert score >= 0.55
