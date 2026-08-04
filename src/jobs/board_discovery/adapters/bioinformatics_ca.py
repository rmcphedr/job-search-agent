"""Bioinformatics.ca jobs adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


class BioinformaticsCaAdapter:
    source_id = "bioinformatics_ca"

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
        search_path = source.search_path or "/jobs"
        search_url = f"{base}{search_path}"

        try:
            html = client.get(search_url, params={"s": query})
        except Exception:
            return candidates

        page_candidates = self._parse_listing(html, source=source, search_url=search_url, base=base, query=query)
        candidates.extend(page_candidates)
        return candidates

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

        for row in soup.select("article, .job, tr, li"):
            title_el = row.select_one("h2 a, h3 a, .entry-title a, a")
            if title_el is None:
                continue
            title = title_el.get_text(" ", strip=True)
            if not title or query_lower not in title.lower():
                continue
            company_el = row.select_one(".company, .employer, .organization")
            location_el = row.select_one(".location")
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
