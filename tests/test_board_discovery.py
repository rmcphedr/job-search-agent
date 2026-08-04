"""Tests for board job discovery."""

from __future__ import annotations

import sqlite3

from src.database.company_upsert import (
    BOARD_DISCOVERED_STATUS,
    placeholder_website,
    upsert_company_from_job,
)
from src.jobs.board_discovery.adapters.biospace import BiospaceAdapter
from src.jobs.board_discovery.adapters.can_acn import CanAcnAdapter
from src.jobs.board_discovery.adapters.healthecareers import HealthecareersAdapter
from src.jobs.board_discovery.adapters.jobbank import JobBankAdapter
from src.jobs.board_discovery.adapters.life_sciences_bc import LifeSciencesBcAdapter
from src.jobs.board_discovery.adapters.neurotechx import NeurotechXAdapter
from src.jobs.board_discovery.ats_enrich import enrich_ats_job_descriptions
from src.jobs.board_discovery.config import BoardSource, boards_need_playwright, load_board_sources_config
from src.jobs.board_discovery.listing_utils import matches_canada_location, matches_query
from src.jobs.job_models import JobCandidate


JOB_BANK_FIXTURE = """
<article id="article-1">
  <a href="/jobsearch/jobposting/12345" class="resultJobItem">
    <span class="noctitle">machine learning specialist</span>
    <li class="business">Vector Institute</li>
    <li class="location"><span class="wb-inv">Location</span> Toronto, ON</li>
  </a>
</article>
"""

BIOSPACE_FIXTURE = """
<li class="lister__item cf">
  <h3 class="lister__header">
    <a href="/job/3064159/sr-machine-learning-engineer/"><span>Sr Machine Learning Engineer</span></a>
  </h3>
  <ul class="lister__meta">
    <li class="lister__meta-item lister__meta-item--location">Toronto, Ontario</li>
    <li class="lister__meta-item lister__meta-item--recruiter">Amgen</li>
  </ul>
</li>
"""

NEUROTECHX_FIXTURE = """
<li class="job_listing">
  <a href="https://neurotechx.com/job/software-engineer/">
    <div class="position"><h3>Software Engineer</h3><div class="company"><strong>Neuranics</strong></div></div>
    <div class="location">Toronto, ON</div>
  </a>
</li>
"""

LSBC_FIXTURE = """
<a href="https://lifesciencesbc.ca/job/marketing-partnerships-manager/">Marketing & Partnerships Manager</a>
"""

CAN_ACN_FIXTURE = """
<h2><a href="https://can-acn.org/tenure-track-assistant-professor-in-neuroethology/">Tenure-Track Assistant Professor in Neuroethology – McMaster</a></h2>
"""

HEALTHECAREERS_FIXTURE = """
<div class="job-results-card">
  <a class="job-title" data-location="Toronto, ON, Canada" href="https://www.healthecareers.com/job/example/1">
    <span>Machine Learning Scientist</span>
  </a>
  <div class="job-vendor">Health AI Labs</div>
</div>
"""


def test_load_board_sources_config_has_essential_boards() -> None:
    config = load_board_sources_config()
    source_ids = {board.source_id for board in config.boards}
    enabled = {board.source_id for board in config.boards if board.enabled}
    playwright_boards = {board.source_id for board in config.boards if board.scrape_mode == "playwright"}
    assert "jobbank" in source_ids
    assert "indeed_ca" in source_ids
    assert "linkedin" in source_ids
    assert "biospace" in source_ids
    assert "jobbank" in enabled
    assert "indeed_ca" in enabled
    assert "indeed_ca" in playwright_boards


def test_jobbank_adapter_parses_fixture() -> None:
    source = BoardSource(
        source_id="jobbank",
        name="Job Bank Canada",
        adapter="jobbank",
        base_url="https://www.jobbank.gc.ca",
        search_path="/jobsearch/jobsearch",
    )
    adapter = JobBankAdapter()
    results = adapter._parse_listing(
        JOB_BANK_FIXTURE,
        source=source,
        search_url="https://www.jobbank.gc.ca/jobsearch/jobsearch",
        base="https://www.jobbank.gc.ca",
    )
    assert len(results) == 1
    assert results[0].title == "machine learning specialist"
    assert results[0].company_name == "Vector Institute"
    assert "jobposting/12345" in (results[0].url or "")


def test_biospace_adapter_parses_fixture() -> None:
    source = BoardSource(
        source_id="biospace",
        name="BioSpace Jobs",
        adapter="biospace",
        base_url="https://jobs.biospace.com",
    )
    adapter = BiospaceAdapter()
    results = adapter._parse_listing(
        BIOSPACE_FIXTURE,
        source=source,
        search_url="https://jobs.biospace.com/jobs/",
        base="https://jobs.biospace.com",
    )
    assert len(results) == 1
    assert results[0].title == "Sr Machine Learning Engineer"
    assert results[0].company_name == "Amgen"
    assert results[0].location == "Toronto, Ontario"


def test_neurotechx_adapter_parses_fixture() -> None:
    source = BoardSource(
        source_id="neurotechx",
        name="NeuroTechX Jobs",
        adapter="neurotechx",
        base_url="https://neurotechx.com",
        search_path="/find-a-job/",
    )
    adapter = NeurotechXAdapter()
    results = adapter._parse_listing(
        NEUROTECHX_FIXTURE,
        source=source,
        search_url="https://neurotechx.com/find-a-job/",
        query="software",
        location_filter="Canada",
    )
    assert len(results) == 1
    assert results[0].title == "Software Engineer"
    assert results[0].company_name == "Neuranics"


def test_life_sciences_bc_adapter_parses_fixture() -> None:
    source = BoardSource(
        source_id="life_sciences_bc",
        name="Life Sciences BC Job Board",
        adapter="life_sciences_bc",
        base_url="https://lifesciencesbc.ca",
    )
    adapter = LifeSciencesBcAdapter()
    results = adapter._parse_listing(
        LSBC_FIXTURE,
        source=source,
        search_url="https://lifesciencesbc.ca/jobs/job-board/",
    )
    assert len(results) == 1
    assert "Marketing" in results[0].title


def test_can_acn_adapter_parses_fixture() -> None:
    source = BoardSource(
        source_id="can_neurojobs",
        name="CAN NeuroJobs",
        adapter="can_acn",
        base_url="https://can-acn.org",
    )
    adapter = CanAcnAdapter()
    results = adapter._parse_listing(
        CAN_ACN_FIXTURE,
        source=source,
        search_url="https://can-acn.org/neuroscience-academic-positions/",
    )
    assert len(results) == 1
    assert "Neuroethology" in results[0].title


def test_healthecareers_adapter_parses_fixture() -> None:
    source = BoardSource(
        source_id="healthecareers",
        name="Health eCareers",
        adapter="healthecareers",
        base_url="https://www.healthecareers.com",
        search_path="/search-jobs",
    )
    adapter = HealthecareersAdapter()
    results = adapter._parse_listing(
        HEALTHECAREERS_FIXTURE,
        source=source,
        search_url="https://www.healthecareers.com/search-jobs",
    )
    assert len(results) == 1
    assert results[0].title == "Machine Learning Scientist"
    assert results[0].company_name == "Health AI Labs"


def test_listing_utils_canada_and_query() -> None:
    assert matches_canada_location("Toronto, ON, Canada") is True
    assert matches_canada_location("Boston, MA") is False
    assert matches_query("Machine Learning Scientist", "machine learning") is True


def test_boards_need_playwright_detects_phase3() -> None:
    config = load_board_sources_config()
    enabled = [board for board in config.boards if board.enabled]
    assert boards_need_playwright(enabled) is True


def test_ats_enrich_skips_non_ats_urls() -> None:
    candidate = JobCandidate(
        company_name="Acme",
        title="Engineer",
        url="https://example.com/jobs/1",
        source_career_page="https://example.com",
        provider="jobbank",
    )
    enriched = enrich_ats_job_descriptions([candidate], max_enrichments=5)
    assert enriched[0].description is None


def test_upsert_company_from_job_creates_placeholder(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE companies (
            company_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            website TEXT NOT NULL UNIQUE,
            industry TEXT,
            location TEXT,
            size TEXT,
            hiring_status TEXT,
            priority TEXT,
            last_checked TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    company_id = upsert_company_from_job(
        connection,
        company_name="New Board Co",
        job_url="https://www.jobbank.gc.ca/jobsearch/jobposting/1",
        location="Montreal, QC",
    )
    connection.commit()

    row = connection.execute(
        "SELECT company_name, website, hiring_status, location FROM companies WHERE company_id = ?;",
        (company_id,),
    ).fetchone()
    connection.close()

    assert row is not None
    assert row["company_name"] == "New Board Co"
    assert row["hiring_status"] == BOARD_DISCOVERED_STATUS
    assert row["location"] == "Montreal, QC"
    assert row["website"] == placeholder_website("New Board Co")
