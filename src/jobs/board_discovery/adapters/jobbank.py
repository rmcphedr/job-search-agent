"""Job Bank Canada adapter."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


class JobBankAdapter:
    source_id = "jobbank"

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
        search_path = source.search_path or "/jobsearch/jobsearch"

        for page in range(1, max_pages + 1):
            params = {
                "searchstring": query,
                "locationstring": location,
                "sort": "M",
                "page": str(page),
            }
            search_url = f"{base}{search_path}"
            html = client.get(search_url, params=params)
            page_candidates = self._parse_listing(html, source=source, search_url=search_url, base=base)
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
        results: list[JobCandidate] = []

        for article in soup.select("article"):
            title_el = article.select_one("span.noctitle")
            company_el = article.select_one("li.business")
            location_el = article.select_one("li.location")
            link_el = article.select_one("a[href*='jobposting']")

            title = title_el.get_text(" ", strip=True) if title_el else None
            company = company_el.get_text(" ", strip=True) if company_el else None
            location = location_el.get_text(" ", strip=True) if location_el else None
            if location:
                location = location.replace("Location", "").strip()
            url = absolute_url(base, link_el.get("href") if link_el else None)

            if not company:
                company = "Unknown employer"

            candidate = build_candidate(
                source=source,
                company_name=company,
                title=title or "",
                location=location,
                url=url,
                search_url=search_url,
            )
            if candidate is not None:
                results.append(candidate)

        return results
