"""Unit tests for career page URL utilities."""

from src.careers.career_url_utils import (
    is_effectively_homepage,
    is_hash_only_career_route,
    looks_like_job_portal_link,
    score_career_url,
)


def test_hash_only_career_route_detected() -> None:
    assert is_hash_only_career_route("https://example.com/#/careers")
    assert is_hash_only_career_route("https://example.com/#careers")
    assert not is_hash_only_career_route("https://example.com/careers")


def test_homepage_not_counted_as_career_page() -> None:
    homepage = "https://example.com"
    assert is_effectively_homepage(homepage, "https://example.com")
    assert is_effectively_homepage(homepage, "https://www.example.com/")
    assert is_effectively_homepage(homepage, "https://example.com/#/careers")
    assert not is_effectively_homepage(homepage, "https://example.com/careers")
    assert not is_effectively_homepage(homepage, "https://careers.example.com/")


def test_score_rejects_homepage_and_hash_routes() -> None:
    homepage = "https://nanofacile.com"
    confidence, notes = score_career_url(
        "https://nanofacile.com/#/careers",
        anchor_text="Careers",
        page_text="Join our team careers jobs hiring",
        final_url="https://nanofacile.com/#/careers",
        homepage=homepage,
    )
    assert confidence == 0.0
    assert "homepage" in notes.lower() or "hash" in notes.lower()


def test_portal_link_terms() -> None:
    assert looks_like_job_portal_link("Current Job Openings", "https://careers.abbvie.com/en")
    assert looks_like_job_portal_link("See current openings", "https://careers.bcit.ca")
    assert looks_like_job_portal_link("See openings", "https://www.abcellera.com/current-openings")
    assert not looks_like_job_portal_link("About us", "https://example.com/about")


def test_ats_and_careers_subdomain_score_high() -> None:
    confidence, notes = score_career_url(
        "https://careers.abbvie.com/en",
        anchor_text="Current Job Openings",
        homepage="https://www.abbvie.ca",
    )
    assert confidence >= 0.90
    assert "ATS" in notes or "subdomain" in notes.lower()
