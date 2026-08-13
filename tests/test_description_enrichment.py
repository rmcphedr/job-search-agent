from __future__ import annotations

import sqlite3
from pathlib import Path

from src.jobs.description_enrichment import (
    DescriptionEnrichmentResult,
    apply_enrichment_result,
    enrich_description,
    mark_job_expired,
)
from src.jobs.enrich_missing_descriptions import list_missing_description_jobs


class FakeBrowser:
    def __init__(self, html: str, *, blocked_reason: str | None = None) -> None:
        self.html = html
        self.blocked_reason = blocked_reason
        self.requested: list[str] = []

    def get_page_html(self, url: str, **kwargs):
        from src.jobs.board_discovery.playwright_client import PlaywrightFetchResult

        self.requested.append(url)
        return PlaywrightFetchResult(
            html=self.html,
            final_url=url,
            blocked_reason=self.blocked_reason,
        )


def test_enriches_description_from_original_posting(monkeypatch, tmp_path: Path) -> None:
    description = "Build reliable machine learning systems. " * 8
    html = f'<html><script type="application/ld+json">{{"@type":"JobPosting","description":"{description}"}}</script></html>'
    monkeypatch.setattr(
        "src.jobs.description_enrichment.fetch_page",
        lambda url: (200, url, html),
    )

    result = enrich_description(
        {"url": "https://jobs.example.com/123", "company_name": "Acme", "title": "Engineer"},
        inventory_path=tmp_path / "missing.csv",
    )

    assert result.status == "enriched"
    assert result.source == "original_posting"
    assert result.description and "machine learning" in result.description


def test_marks_gone_posting_expired(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.jobs.description_enrichment.fetch_page",
        lambda url: (410, url, ""),
    )

    result = enrich_description(
        {"url": "https://jobs.example.com/123", "company_name": "Acme", "title": "Engineer"},
        inventory_path=tmp_path / "missing.csv",
    )

    assert result.status == "expired"


def test_fetch_failure_is_retryable_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.jobs.description_enrichment.fetch_page",
        lambda url: (0, url, ""),
    )

    result = enrich_description(
        {"url": "https://jobs.example.com/123", "company_name": "Acme", "title": "Engineer"},
        inventory_path=tmp_path / "missing.csv",
    )

    assert result.status == "error"
    assert "retry" in (result.error or "").lower()


def test_repairs_legacy_biospace_url(monkeypatch, tmp_path: Path) -> None:
    requested_urls: list[str] = []

    def fetch(url: str):
        requested_urls.append(url)
        return 404, url, ""

    monkeypatch.setattr("src.jobs.description_enrichment.fetch_page", fetch)
    enrich_description(
        {
            "url": "https:///job/3064185/example",
            "source_board": "biospace",
            "company_name": "Acme",
            "title": "Engineer",
        },
        inventory_path=tmp_path / "missing.csv",
    )

    assert requested_urls == ["https://jobs.biospace.com/job/3064185/example"]


def test_linkedin_lead_is_not_fetched_directly(monkeypatch, tmp_path: Path) -> None:
    def fail_fetch(url: str):
        raise AssertionError(f"LinkedIn should not be fetched directly: {url}")

    monkeypatch.setattr("src.jobs.description_enrichment.fetch_page", fail_fetch)
    result = enrich_description(
        {
            "url": "https://www.linkedin.com/jobs/view/123",
            "company_name": "Acme",
            "title": "Engineer",
        },
        inventory_path=tmp_path / "missing.csv",
    )

    assert result.status == "not_found"
    assert result.source == "employer_lookup"


def test_linkedin_lead_uses_rendered_browser_description(monkeypatch, tmp_path: Path) -> None:
    def fail_fetch(url: str):
        raise AssertionError(f"LinkedIn should not use the HTTP fetcher: {url}")

    description = "Develop production machine learning models and partner with scientists. " * 4
    browser = FakeBrowser(f'<div class="show-more-less-html__markup">{description}</div>')
    monkeypatch.setattr("src.jobs.description_enrichment.fetch_page", fail_fetch)

    result = enrich_description(
        {
            "url": "https://www.linkedin.com/jobs/view/123",
            "source_board": "linkedin",
            "company_name": "Acme",
            "title": "Engineer",
        },
        inventory_path=tmp_path / "missing.csv",
        browser=browser,
    )

    assert result.status == "enriched"
    assert result.source == "browser_rendered_posting"
    assert browser.requested == ["https://www.linkedin.com/jobs/view/123"]


def test_eluta_http_failure_falls_back_to_rendered_browser(monkeypatch, tmp_path: Path) -> None:
    description = "Design bioinformatics pipelines and analyze experimental datasets. " * 4
    browser = FakeBrowser(f'<main><div class="job-description">{description}</div></main>')
    monkeypatch.setattr(
        "src.jobs.description_enrichment.fetch_page",
        lambda url: (0, url, ""),
    )

    result = enrich_description(
        {
            "url": "https://www.eluta.ca/spl/example",
            "source_board": "eluta",
            "company_name": "Acme",
            "title": "Scientist",
        },
        inventory_path=tmp_path / "missing.csv",
        browser=browser,
    )

    assert result.status == "enriched"
    assert result.source == "browser_rendered_posting"


def _database(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "jobs.db")
    connection.row_factory = sqlite3.Row
    schema = Path("src/database/schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)
    return connection


def test_expired_job_is_deactivated_and_withdrawn(monkeypatch, tmp_path: Path) -> None:
    connection = _database(tmp_path)
    connection.execute("INSERT INTO companies (company_id, company_name, website) VALUES (1, 'Acme', 'https://acme.test')")
    connection.execute(
        "INSERT INTO job_postings (job_id, company_id, title, url) VALUES (1, 1, 'Engineer', 'https://acme.test/job')"
    )
    connection.execute("INSERT INTO tracked_jobs (job_id, stage) VALUES (1, 'tracked')")
    connection.commit()
    connection.close()
    def connect() -> sqlite3.Connection:
        result = sqlite3.connect(tmp_path / "jobs.db")
        result.row_factory = sqlite3.Row
        return result

    monkeypatch.setattr("src.jobs.description_enrichment.get_connection", connect)

    mark_job_expired(1)

    check = sqlite3.connect(tmp_path / "jobs.db")
    job = check.execute("SELECT active, description_status FROM job_postings WHERE job_id = 1").fetchone()
    tracked = check.execute("SELECT stage FROM tracked_jobs WHERE job_id = 1").fetchone()
    check.close()
    assert job == (0, "expired")
    assert tracked == ("withdrawn",)


def test_missing_jobs_prioritize_review_inbox(monkeypatch, tmp_path: Path) -> None:
    connection = _database(tmp_path)
    connection.execute("INSERT INTO companies (company_id, company_name, website) VALUES (1, 'Acme', 'https://acme.test')")
    jobs = [
        (1, "Review fit", 8.0, 7.0),
        (2, "Other untracked", None, 9.0),
        (3, "Already tracked", 10.0, 10.0),
    ]
    for job_id, title, fit_score, keyword_score in jobs:
        connection.execute(
            "INSERT INTO job_postings (job_id, company_id, title, url, fit_score, keyword_score) VALUES (?, 1, ?, ?, ?, ?)",
            (job_id, title, f"https://acme.test/{job_id}", fit_score, keyword_score),
        )
    connection.execute("INSERT INTO tracked_jobs (job_id, stage) VALUES (3, 'tracked')")
    connection.commit()
    connection.close()

    def connect() -> sqlite3.Connection:
        result = sqlite3.connect(tmp_path / "jobs.db")
        result.row_factory = sqlite3.Row
        return result

    monkeypatch.setattr("src.jobs.enrich_missing_descriptions.get_connection", connect)
    selected = list_missing_description_jobs(limit=10)

    assert [job["job_id"] for job in selected] == [1, 2, 3]
    assert [job["enrichment_priority"] for job in selected] == [0, 1, 2]


def test_missing_jobs_can_be_limited_to_tracked(monkeypatch, tmp_path: Path) -> None:
    connection = _database(tmp_path)
    connection.execute("INSERT INTO companies (company_id, company_name, website) VALUES (1, 'Acme', 'https://acme.test')")
    for job_id in (1, 2):
        connection.execute(
            "INSERT INTO job_postings (job_id, company_id, title, url) VALUES (?, 1, ?, ?)",
            (job_id, f"Job {job_id}", f"https://acme.test/{job_id}"),
        )
    connection.execute("INSERT INTO tracked_jobs (job_id, stage) VALUES (2, 'tracked')")
    connection.commit()
    connection.close()

    def connect() -> sqlite3.Connection:
        result = sqlite3.connect(tmp_path / "jobs.db")
        result.row_factory = sqlite3.Row
        return result

    monkeypatch.setattr("src.jobs.enrich_missing_descriptions.get_connection", connect)

    selected = list_missing_description_jobs(limit=10, only_tracked=True)

    assert [job["job_id"] for job in selected] == [2]
