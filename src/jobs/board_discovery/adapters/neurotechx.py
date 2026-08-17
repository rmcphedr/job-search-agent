"""NeuroTechX jobs adapter (WP Job Manager)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import build_candidate
from src.jobs.job_models import JobCandidate


class NeurotechXAdapter:
    source_id = "neurotechx"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        search_path = source.search_path or "/find-a-job/"
        base = source.base_url.rstrip("/")
        search_url = f"{base}{search_path}"

        try:
            html, final_url = client.get_with_url(search_url)
        except Exception:
            return []

        return self._parse_listing(
            html,
            source=source,
            search_url=final_url,
            query=query,
            location_filter=location,
        )

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
        query: str,
        location_filter: str,
    ) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobCandidate] = []
        query_lower = query.lower()
        location_lower = location_filter.lower()

        for card in soup.select("li.job_listing"):
            link = card.select_one("a[href*='/job/']")
            title_el = card.select_one("h3")
            company_el = card.select_one(".company")
            location_el = card.select_one(".location")

            title = title_el.get_text(" ", strip=True) if title_el else None
            if not title:
                continue

            blob = card.get_text(" ", strip=True).lower()
            if query_lower not in blob and query_lower not in title.lower():
                continue

            company = company_el.get_text(" ", strip=True) if company_el else "Unknown employer"
            location_text = location_el.get_text(" ", strip=True) if location_el else None

            if location_lower == "canada":
                canada_markers = ("canada", ", on", ", qc", ", bc", ", ab", "toronto", "montreal", "vancouver")
                if location_text and not any(marker in location_text.lower() for marker in canada_markers):
                    # NeuroTechX is global; keep non-Canada only when query matches strongly in title
                    if query_lower not in title.lower():
                        continue

            url = link.get("href") if link else None
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
