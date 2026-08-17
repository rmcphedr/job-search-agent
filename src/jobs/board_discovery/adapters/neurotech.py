"""Neurotech Jobs (neurotechjobs.io) adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


class NeurotechAdapter:
    source_id = "neurotech"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        base = source.base_url.rstrip("/")
        search_url = f"{base}/#search-jobs"
        try:
            html = client.get(base)
        except Exception:
            return []

        return self._parse_listing(html, source=source, search_url=search_url, base=base, query=query)

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
        base: str,
        query: str,
    ) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobCandidate] = []
        query_lower = query.lower()

        for card in soup.select("div.job, article, .job-card, li"):
            title_el = card.select_one("h2 a, h3 a, .job-title a, a")
            if title_el is None:
                continue
            title = title_el.get_text(" ", strip=True)
            if not title:
                continue
            blob = card.get_text(" ", strip=True).lower()
            if query_lower not in blob and query_lower not in title.lower():
                continue

            company_el = card.select_one(".company, .employer, .organization")
            location_el = card.select_one(".location, .city")
            company = company_el.get_text(" ", strip=True) if company_el else "Unknown employer"
            location_text = location_el.get_text(" ", strip=True) if location_el else None
            url = absolute_url(base, title_el.get("href"))

            candidate = build_candidate(
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
