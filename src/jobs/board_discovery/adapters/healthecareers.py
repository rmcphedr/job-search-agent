"""Health eCareers search adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.listing_utils import filter_listing_candidates, make_listing_candidate
from src.jobs.job_models import JobCandidate


class HealthecareersAdapter:
    source_id = "healthecareers"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        candidates: list[JobCandidate] = []
        base = source.base_url.rstrip("/")
        search_path = source.search_path or "/search-jobs"

        for page in range(1, max_pages + 1):
            params = {
                "q": query,
                "l": location if location.lower() != "canada" else "Canada",
                "page": str(page),
            }
            search_url = f"{base}{search_path}"
            try:
                html, final_url = client.get_with_url(search_url, params=params)
            except Exception:
                break
            page_candidates = self._parse_listing(html, source=source, search_url=final_url)
            if not page_candidates:
                break
            candidates.extend(page_candidates)

        return filter_listing_candidates(candidates, query=query, require_canada=True)

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
    ) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobCandidate] = []

        for card in soup.select(".job-results-card"):
            title_el = card.select_one("a.job-title")
            if title_el is None:
                continue
            title = title_el.get_text(" ", strip=True)
            if not title:
                continue

            location_text = title_el.get("data-location")
            if not location_text:
                location_el = card.select_one(".job-location")
                location_text = location_el.get_text(" ", strip=True) if location_el else None

            company_el = card.select_one(".job-vendor")
            company = company_el.get_text(" ", strip=True) if company_el else "Unknown employer"
            url = title_el.get("href")

            candidate = make_listing_candidate(
                source=source,
                company_name=company,
                title=title,
                location=location_text,
                url=url,
                search_url=search_url,
            )
            if candidate is not None:
                results.append(candidate)

        return results
