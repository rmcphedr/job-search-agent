"""Google Jobs rendered-results adapter."""

from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


class GoogleJobsAdapter:
    """Parse Google Jobs cards; searching is delegated to the Playwright variant."""

    source_id = "google_jobs"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
        browser=None,
    ) -> list[JobCandidate]:
        del query, location, source, client, max_pages, browser
        return []

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
        base: str,
    ) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobCandidate] = []
        seen: set[tuple[str, str]] = set()

        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            for job in _walk_job_postings(payload):
                organization = job.get("hiringOrganization") or {}
                location = job.get("jobLocation") or {}
                address = location.get("address") if isinstance(location, dict) else {}
                if not isinstance(address, dict):
                    address = {}
                location_text = ", ".join(
                    str(address.get(key)).strip()
                    for key in ("addressLocality", "addressRegion", "addressCountry")
                    if address.get(key)
                ) or None
                candidate = build_candidate(
                    source=source,
                    company_name=str(organization.get("name") or "Unknown employer"),
                    title=str(job.get("title") or ""),
                    location=location_text,
                    url=absolute_url(base, job.get("url")),
                    search_url=search_url,
                )
                if candidate is not None:
                    results.append(candidate)

        card_selectors = (
            "[data-job-id], div[jsname='x5pWN'], div[class*='PwjeAc'], "
            "li[class*='iFjolb']"
        )
        for card in soup.select(card_selectors):
            title_el = card.select_one(
                "[data-testid='job-title'], [class*='BjJfJf'], h2, h3"
            )
            company_el = card.select_one(
                "[data-testid='company-name'], [class*='vNEEBe'], [class*='company']"
            )
            location_el = card.select_one(
                "[data-testid='job-location'], [class*='Qk80Jf'], [class*='location']"
            )
            link = card.select_one("a[href]")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            company = company_el.get_text(" ", strip=True) if company_el else "Unknown employer"
            key = (title.lower(), company.lower())
            if not title or key in seen:
                continue
            seen.add(key)
            candidate = build_candidate(
                source=source,
                company_name=company,
                title=title,
                location=location_el.get_text(" ", strip=True) if location_el else None,
                url=absolute_url(base, link.get("href") if link else None) or search_url,
                search_url=search_url,
            )
            if candidate is not None:
                results.append(candidate)
        return results


def _walk_job_postings(value: Any):
    if isinstance(value, dict):
        if value.get("@type") == "JobPosting":
            yield value
        for child in value.values():
            yield from _walk_job_postings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_job_postings(child)
