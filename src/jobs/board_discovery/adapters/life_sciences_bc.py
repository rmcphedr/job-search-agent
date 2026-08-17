"""Life Sciences BC job board adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.listing_utils import make_listing_candidate
from src.jobs.board_discovery.parsers import absolute_url
from src.jobs.job_models import JobCandidate

LISTING_URL = "https://lifesciencesbc.ca/jobs/job-board/"


class LifeSciencesBcAdapter:
    source_id = "life_sciences_bc"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        del max_pages  # Single listing page today.
        try:
            html, final_url = client.get_with_url(LISTING_URL)
        except Exception:
            return []

        candidates = self._parse_listing(html, source=source, search_url=final_url)
        return candidates

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
    ) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobCandidate] = []
        seen_urls: set[str] = set()

        for anchor in soup.select('a[href*="/job/"]'):
            href = absolute_url(source.base_url, anchor.get("href"))
            if not href or href in seen_urls:
                continue
            title = anchor.get_text(" ", strip=True)
            if not title or len(title) < 4:
                continue
            seen_urls.add(href)

            company = "Unknown employer"
            location_text: str | None = None
            parent = anchor.find_parent(["li", "article", "div"])
            if parent:
                blob = parent.get_text(" ", strip=True)
                if "|" in blob:
                    parts = [part.strip() for part in blob.split("|") if part.strip()]
                    if len(parts) >= 2:
                        location_text = parts[1] if "bc" in parts[1].lower() or "," in parts[1] else None

            candidate = make_listing_candidate(
                source=source,
                company_name=company,
                title=title,
                location=location_text or "British Columbia, Canada",
                url=href,
                search_url=search_url,
            )
            if candidate is not None:
                results.append(candidate)

        return results
