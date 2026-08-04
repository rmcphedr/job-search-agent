"""Indeed Canada adapter."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


class IndeedCaAdapter:
    source_id = "indeed_ca"

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

        for page_index in range(max_pages):
            params = {
                "q": query,
                "l": source.search_params.get("l", location),
                "start": str(page_index * 10),
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

        cards = soup.select("div.job_seen_beacon, div.cardOutline, td.resultContent")
        if not cards:
            cards = soup.select("a[href*='/rc/clk'], a[href*='/viewjob']")

        for card in cards:
            title_el = card.select_one("h2.jobTitle span, h2.jobTitle a, a.jcs-JobTitle")
            company_el = card.select_one("[data-testid='company-name'], span.companyName")
            location_el = card.select_one("[data-testid='text-location'], div.companyLocation")
            link_el = card.select_one("a[href*='/viewjob'], a[href*='/rc/clk'], h2.jobTitle a")

            title = title_el.get_text(" ", strip=True) if title_el else None
            company = company_el.get_text(" ", strip=True) if company_el else None
            location = location_el.get_text(" ", strip=True) if location_el else None
            url = absolute_url(base, link_el.get("href") if link_el else None)
            if url:
                url = re.sub(r"&from=.*", "", url)

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
