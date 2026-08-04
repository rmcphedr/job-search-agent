"""Eluta Canada adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


class ElutaAdapter:
    source_id = "eluta"

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
        search_path = source.search_path or "/search"

        for page in range(1, max_pages + 1):
            params = {
                "q": query,
                "l": location,
                "page": str(page),
            }
            search_url = f"{base}{search_path}"
            try:
                html = client.get(search_url, params=params)
            except Exception:
                break
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

        for row in soup.select("div.job, tr.job, article.job, .result"):
            title_el = row.select_one("a.title, h2 a, h3 a, .job-title a")
            company_el = row.select_one(".company, .employer, .org")
            location_el = row.select_one(".location, .city")

            title = title_el.get_text(" ", strip=True) if title_el else None
            company = company_el.get_text(" ", strip=True) if company_el else None
            location_text = location_el.get_text(" ", strip=True) if location_el else None
            url = absolute_url(base, title_el.get("href") if title_el else None)

            if not company:
                company = "Unknown employer"

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
