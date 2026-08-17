"""Glassdoor Canada board adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


class GlassdoorAdapter:
    """Search and parse Glassdoor listings using rendered or static HTML."""

    source_id = "glassdoor"

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
        del browser
        candidates: list[JobCandidate] = []
        base = source.base_url.rstrip("/")
        search_url = f"{base}{source.search_path or '/Job/jobs.htm'}"
        resolved_location = source.search_params.get("location", location)

        for page in range(1, max_pages + 1):
            params = {
                "sc.keyword": query,
                "locT": source.search_params.get("locT", "N"),
                "locId": source.search_params.get("locId", "3"),
                "p": str(page),
            }
            if resolved_location:
                params["location"] = resolved_location
            try:
                html = client.get(search_url, params=params)
            except Exception:
                break
            page_candidates = self._parse_listing(
                html, source=source, search_url=search_url, base=base
            )
            if not page_candidates:
                break
            candidates.extend(page_candidates)
        return candidates

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
        base: str,
    ) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(
            "li[data-test='jobListing'], li[class*='JobsList_jobListItem'], "
            "div[class*='JobCard_jobCardContainer'], article[data-test='job-card']"
        )
        results: list[JobCandidate] = []

        for card in cards:
            title_el = card.select_one(
                "a[data-test='job-title'], a[class*='JobCard_jobTitle'], "
                "a[href*='/job-listing/'], a[href*='/partner/jobListing']"
            )
            company_el = card.select_one(
                "[data-test='employer-name'], [class*='EmployerProfile_employerName'], "
                "[class*='EmployerProfile_compactEmployerName']"
            )
            location_el = card.select_one(
                "[data-test='emp-location'], [data-test='job-location'], "
                "[class*='JobCard_location']"
            )
            title = title_el.get_text(" ", strip=True) if title_el else None
            company = company_el.get_text(" ", strip=True) if company_el else "Unknown employer"
            location_text = location_el.get_text(" ", strip=True) if location_el else None
            url = absolute_url(base, title_el.get("href") if isinstance(title_el, Tag) else None)
            candidate = build_candidate(
                source=source,
                company_name=company,
                title=title or "",
                location=location_text,
                url=url,
                search_url=search_url,
            )
            if candidate is not None:
                results.append(candidate)
        return results
