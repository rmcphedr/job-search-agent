"""Unit tests for job detail parsing and location extraction."""

from src.jobs.job_detail_parsers import parse_job_detail_from_html
from src.jobs.job_url_utils import is_work_location_type, location_from_job_url


def test_location_from_abbvie_job_url() -> None:
    url = "https://careers.abbvie.com/en/job/lead-machine-learning-engineer-in-san-diego-ca-jid-28673"
    assert location_from_job_url(url) == "San Diego, CA"


def test_work_location_type_detection() -> None:
    assert is_work_location_type("Hybrid")
    assert is_work_location_type("remote")
    assert not is_work_location_type("San Diego, CA")


def test_parse_abbvie_json_ld_location() -> None:
    html = """
    <html><body>
    <p class="attrax-job-information-widget__freetext-field-value">San Diego, CA</p>
    <label class="Worklocationtype">Work location type:</label>
    <li class="Worklocationtype-wrapper">Remote</li>
    <script type="application/ld+json">
    {
      "@context": "http://schema.org",
      "@type": "JobPosting",
      "title": "Lead Machine Learning Engineer",
      "description": "<p><strong>Responsibilities</strong></p><p>Build models.</p>",
      "jobLocation": {
        "@type": "Place",
        "address": {
          "@type": "PostalAddress",
          "addressLocality": "San Diego",
          "addressRegion": "CA"
        }
      }
    }
    </script>
    </body></html>
    """
    parsed = parse_job_detail_from_html(
        html,
        "https://careers.abbvie.com/en/job/lead-machine-learning-engineer-in-san-diego-ca-jid-28673",
    )
    assert parsed["title"] == "Lead Machine Learning Engineer"
    assert parsed["location"] == "San Diego, CA"
    assert parsed["location_type"] == "Remote"
    assert parsed["description_raw"] is not None
    assert "Responsibilities" in parsed["description_raw"]
