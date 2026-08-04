"""Canadian Association for Neuroscience job listings adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.listing_utils import make_listing_candidate
from src.jobs.board_discovery.parsers import absolute_url
from src.jobs.job_models import JobCandidate

LISTING_PAGES = (
    "https://can-acn.org/neuroscience-academic-positions/",
    "https://can-acn.org/neurojobs/administrative-positions/",
)


SKIP_TITLES = frozenset(
    {
        "canadian association for neuroscience",
        "neurojobs",
        "opportunities",
    }
)


class CanAcnAdapter:
    source_id = "can_acn"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        del max_pages
        candidates: list[JobCandidate] = []
        seen_urls: set[str] = set()

        for listing_url in LISTING_PAGES:
            try:
                html, final_url = client.get_with_url(listing_url)
            except Exception:
                continue
            for candidate in self._parse_listing(html, source=source, search_url=final_url):
                key = candidate.url or candidate.title
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                candidates.append(candidate)

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

        for anchor in soup.select("h2 a, h3 a, .entry-title a"):
            href = absolute_url(source.base_url, anchor.get("href"))
            if not href or "can-acn.org" not in href:
                continue
            if any(skip in href for skip in ("/category/", "/tag/", "/neurojobs/", "/feed/")):
                continue
            title = anchor.get_text(" ", strip=True)
            if not title or len(title) < 12:
                continue
            if title.strip().lower() in SKIP_TITLES:
                continue

            company = "Canadian academic / research employer"
            location_text = "Canada"
            parent = anchor.find_parent("article") or anchor.find_parent("li")
            if parent:
                blob = parent.get_text(" ", strip=True)
                for marker in ("Montreal", "Toronto", "Vancouver", "Ottawa", "Canada", "Windsor", "Hamilton"):
                    if marker in blob:
                        location_text = marker if marker != "Canada" else "Canada"
                        break

            candidate = make_listing_candidate(
                source=source,
                company_name=company,
                title=title,
                location=location_text,
                url=href,
                search_url=search_url,
            )
            if candidate is not None:
                results.append(candidate)

        return results
