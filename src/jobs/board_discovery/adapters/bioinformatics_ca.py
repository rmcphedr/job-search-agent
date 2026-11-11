"""Bioinformatics.ca jobs adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import build_candidate
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
        del query, location, max_pages
        base = source.base_url.rstrip("/")
        search_path = source.search_path or "/Jobs/"
        search_url = f"{base}{search_path}"
        html, final_url = client.get_with_url(search_url)
        return self._parse_listing(html, source=source, search_url=final_url)

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
    ) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobCandidate] = []

        for row in soup.select("article.biohub-psc-card--job"):
            title_el = row.select_one("h3.biohub-psc-card__title a[href]")
            if title_el is None:
                continue
            title = title_el.get_text(" ", strip=True)
            url = str(title_el.get("href") or "")
            if not title or "/en/jobs/" not in url:
                continue
            attrs = row.select(".biohub-psc-card__attr span")
            if len(attrs) < 2:
                continue
            location_text = attrs[0].get_text(" ", strip=True)
            company = attrs[1].get_text(" ", strip=True)
            if not location_text or not company:
                continue

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
