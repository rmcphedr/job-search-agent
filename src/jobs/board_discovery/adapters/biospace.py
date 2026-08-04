"""BioSpace jobs adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


class BiospaceAdapter:
    source_id = "biospace"

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
        search_path = source.search_path or "/jobs/"

        for page in range(1, max_pages + 1):
            params = dict(source.search_params)
            params.update(
                {
                    "keywords": query,
                    "page": str(page),
                }
            )
            search_url = f"{base}{search_path}"
            try:
                html, final_url = client.get_with_url(search_url, params=params)
            except Exception:
                break
            page_base = final_url.split("/jobs")[0] if "/jobs" in final_url else base
            page_candidates = self._parse_listing(
                html,
                source=source,
                search_url=final_url,
                base=page_base,
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
        results: list[JobCandidate] = []

        for card in soup.select("li.lister__item"):
            title_el = card.select_one("h3 a")
            if title_el is None:
                continue

            title = title_el.get_text(" ", strip=True)
            company_el = card.select_one(".lister__meta-item--recruiter")
            location_el = card.select_one(".lister__meta-item--location")
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
