from __future__ import annotations

from src.jobs.board_discovery.adapters.glassdoor import GlassdoorAdapter
from src.jobs.board_discovery.adapters.indeed_ca import IndeedCaAdapter
from src.jobs.board_discovery.adapters.google_jobs import GoogleJobsAdapter
from src.jobs.board_discovery.adapters.workopolis import WorkopolisAdapter
from src.jobs.board_discovery.config import BoardSource, load_board_sources_config
from src.jobs.board_discovery.playwright_adapters import (
    PlaywrightGlassdoorAdapter,
    PlaywrightIndeedCaAdapter,
    PlaywrightGoogleJobsAdapter,
)
from src.jobs.board_discovery.registry import get_adapter


INDEED_FIXTURE = """
<div data-testid="slider_item">
  <h2 class="jobTitle">
    <a data-testid="jobTitle" href="/viewjob?jk=abc123&from=search">
      <span title="Machine Learning Engineer">Machine Learning Engineer</span>
    </a>
  </h2>
  <span data-testid="company-name">Vector AI</span>
  <div data-testid="text-location">Toronto, ON</div>
</div>
"""


GLASSDOOR_FIXTURE = """
<li data-test="jobListing">
  <a data-test="job-title" href="/job-listing/data-scientist-acme-JV_IC2281069.htm">
    Data Scientist
  </a>
  <span data-test="employer-name">Acme Health</span>
  <div data-test="emp-location">Montreal, QC</div>
</li>
"""

GOOGLE_JOBS_FIXTURE = """
<div data-job-id="google-123">
  <h2>Applied Machine Learning Scientist</h2>
  <div data-testid="company-name">Example AI</div>
  <div data-testid="job-location">Toronto, ON</div>
  <a href="https://example.ai/jobs/123">View job</a>
</div>
"""

WORKOPOLIS_FIXTURE = """
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [{
    "@type": "JobPosting",
    "title": "Senior Data Scientist",
    "url": "https://www.workopolis.com/job/abc123",
    "hiringOrganization": {"@type": "Organization", "name": "Acme Health"},
    "jobLocation": {
      "@type": "Place",
      "address": {
        "@type": "PostalAddress",
        "addressLocality": "Montreal",
        "addressRegion": "QC",
        "addressCountry": "Canada"
      }
    }
  }]
}
</script>
"""


def test_indeed_adapter_parses_current_card_markup() -> None:
    source = BoardSource(
        source_id="indeed_ca",
        name="Indeed Canada",
        adapter="indeed_ca",
        base_url="https://ca.indeed.com",
        search_path="/jobs",
    )
    jobs = IndeedCaAdapter()._parse_listing(
        INDEED_FIXTURE,
        source=source,
        search_url="https://ca.indeed.com/jobs?q=machine+learning",
        base=source.base_url,
    )

    assert len(jobs) == 1
    assert jobs[0].title == "Machine Learning Engineer"
    assert jobs[0].company_name == "Vector AI"
    assert jobs[0].location == "Toronto, ON"
    assert jobs[0].url == "https://ca.indeed.com/viewjob?jk=abc123"


def test_glassdoor_adapter_parses_listing() -> None:
    source = BoardSource(
        source_id="glassdoor",
        name="Glassdoor Canada",
        adapter="glassdoor",
        base_url="https://www.glassdoor.ca",
        search_path="/Job/jobs.htm",
    )
    jobs = GlassdoorAdapter()._parse_listing(
        GLASSDOOR_FIXTURE,
        source=source,
        search_url="https://www.glassdoor.ca/Job/jobs.htm",
        base=source.base_url,
    )

    assert len(jobs) == 1
    assert jobs[0].title == "Data Scientist"
    assert jobs[0].company_name == "Acme Health"
    assert jobs[0].location == "Montreal, QC"
    assert jobs[0].provider == "glassdoor"


def test_registry_selects_request_and_playwright_adapters() -> None:
    assert isinstance(get_adapter("indeed_ca"), IndeedCaAdapter)
    assert isinstance(get_adapter("glassdoor"), GlassdoorAdapter)
    assert isinstance(
        get_adapter("indeed_ca", scrape_mode="playwright"), PlaywrightIndeedCaAdapter
    )
    assert isinstance(
        get_adapter("glassdoor", scrape_mode="playwright"), PlaywrightGlassdoorAdapter
    )
    assert isinstance(get_adapter("workopolis"), WorkopolisAdapter)
    assert isinstance(get_adapter("google_jobs"), GoogleJobsAdapter)
    assert isinstance(
        get_adapter("google_jobs", scrape_mode="playwright"), PlaywrightGoogleJobsAdapter
    )


def test_general_board_config_enables_both_playwright_adapters() -> None:
    sources = {source.source_id: source for source in load_board_sources_config().boards}

    for source_id in ("indeed_ca", "glassdoor", "google_jobs"):
        source = sources[source_id]
        assert source.enabled is True
        assert source.scrape_mode == "playwright"
        assert source.adapter == source_id

    assert sources["workopolis"].enabled is True
    assert sources["workopolis"].adapter == "workopolis"


def test_google_jobs_adapter_parses_rendered_card() -> None:
    source = BoardSource(
        source_id="google_jobs",
        name="Google Jobs",
        adapter="google_jobs",
        base_url="https://www.google.com",
    )
    jobs = GoogleJobsAdapter()._parse_listing(
        GOOGLE_JOBS_FIXTURE,
        source=source,
        search_url="https://www.google.com/search?q=machine+learning+jobs+Canada",
        base=source.base_url,
    )

    assert len(jobs) == 1
    assert jobs[0].title == "Applied Machine Learning Scientist"
    assert jobs[0].company_name == "Example AI"
    assert jobs[0].location == "Toronto, ON"


def test_workopolis_adapter_parses_structured_job_posting() -> None:
    source = BoardSource(
        source_id="workopolis",
        name="Workopolis",
        adapter="workopolis",
        base_url="https://www.workopolis.com",
    )
    jobs = WorkopolisAdapter()._parse_listing(
        WORKOPOLIS_FIXTURE,
        source=source,
        search_url="https://www.workopolis.com/search?q=data+scientist&l=Canada",
        base=source.base_url,
    )

    assert len(jobs) == 1
    assert jobs[0].title == "Senior Data Scientist"
    assert jobs[0].company_name == "Acme Health"
    assert jobs[0].location == "Montreal, QC, Canada"
