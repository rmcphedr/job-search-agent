"""Eluta Canada adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


def parse_eluta_listing(
    html: str,
    *,
    source: BoardSource,
    search_url: str,
    base: str,
) -> list[JobCandidate]:
    """Parse Eluta search results (organic + sponsored listings)."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[JobCandidate] = []
    seen: set[str] = set()

    rows = soup.select("div.organic-job, div.sponsored-job, div[data-url^='spl/']")
    if not rows:
        rows = soup.select("div.job, tr.job, article.job, .result")

    for row in rows:
        title_el = row.select_one("a.lk-job-title, a.title, h2 a, h3 a, .job-title a")
        company_el = row.select_one("a.employer.lk-employer, .company, .employer, .org")
        location_el = row.select_one("span.location span, .location, .city")

        title = None
        if title_el is not None:
            title = title_el.get("title") or title_el.get_text(" ", strip=True)
        company = company_el.get_text(" ", strip=True) if company_el else None
        location_text = location_el.get_text(" ", strip=True) if location_el else None

        data_url = row.get("data-url") or (title_el.get("data-url") if title_el else None)
        href = title_el.get("href") if title_el else None
        if data_url:
            url = absolute_url(base, data_url if data_url.startswith("/") else f"/{data_url}")
        else:
            url = absolute_url(base, href)

        if not company:
            company = "Unknown employer"
        if not title:
            continue

        dedupe_key = f"{title.lower()}|{company.lower()}|{url or ''}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

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
        resolved_location = source.search_params.get("l", location)

        for page in range(1, max_pages + 1):
            params = {
                "q": query,
                "l": resolved_location,
                "page": str(page),
            }
            search_url = f"{base}{search_path}"
            try:
                html = client.get(search_url, params=params)
            except Exception:
                break
            page_candidates = parse_eluta_listing(html, source=source, search_url=search_url, base=base)
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
        return parse_eluta_listing(html, source=source, search_url=search_url, base=base)
