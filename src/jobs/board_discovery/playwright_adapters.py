"""Playwright-backed adapters for anti-bot job boards (phase 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from src.jobs.board_discovery.adapters.indeed_ca import IndeedCaAdapter
from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate

if TYPE_CHECKING:
    from src.jobs.board_discovery.playwright_client import PlaywrightBrowserClient


def _require_browser(browser: PlaywrightBrowserClient | None) -> PlaywrightBrowserClient:
    if browser is None:
        raise RuntimeError("Playwright browser is required for this adapter.")
    return browser


class PlaywrightIndeedCaAdapter(IndeedCaAdapter):
    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
        browser: PlaywrightBrowserClient | None = None,
    ) -> list[JobCandidate]:
        del client
        pw = _require_browser(browser)
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
            result = pw.get_page_html(
                search_url,
                params=params,
                wait_selector=source.wait_selector or ".job_seen_beacon, .jobsearch-ResultsList",
            )
            page_candidates = self._parse_listing(
                result.html,
                source=source,
                search_url=result.final_url,
                base=base,
            )
            if not page_candidates:
                break
            candidates.extend(page_candidates)
        return candidates


class PlaywrightElutaAdapter:
    source_id = "eluta"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
        browser: PlaywrightBrowserClient | None = None,
    ) -> list[JobCandidate]:
        del client
        pw = _require_browser(browser)
        candidates: list[JobCandidate] = []
        base = source.base_url.rstrip("/")
        search_path = source.search_path or "/search"

        for page in range(1, max_pages + 1):
            params = {"q": query, "l": location, "page": str(page)}
            search_url = f"{base}{search_path}"
            result = pw.get_page_html(search_url, params=params, wait_selector=source.wait_selector)
            page_candidates = self._parse_listing(result.html, source=source, search_url=result.final_url, base=base)
            if not page_candidates:
                break
            candidates.extend(page_candidates)
        return candidates

    def _parse_listing(self, html: str, *, source: BoardSource, search_url: str, base: str) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobCandidate] = []
        for row in soup.select("div.job, tr.job, article.job, .result, li.result"):
            title_el = row.select_one("a.title, h2 a, h3 a, .job-title a, a[href*='job']")
            company_el = row.select_one(".company, .employer, .org")
            location_el = row.select_one(".location, .city")
            title = title_el.get_text(" ", strip=True) if title_el else None
            company = company_el.get_text(" ", strip=True) if company_el else "Unknown employer"
            location_text = location_el.get_text(" ", strip=True) if location_el else None
            url = absolute_url(base, title_el.get("href") if title_el else None)
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


class PlaywrightWellfoundAdapter:
    source_id = "wellfound"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
        browser: PlaywrightBrowserClient | None = None,
    ) -> list[JobCandidate]:
        del client
        pw = _require_browser(browser)
        base = source.base_url.rstrip("/")
        search_path = source.search_path or "/jobs"
        params = {"query": query, "location": location}
        search_url = f"{base}{search_path}"
        result = pw.get_page_html(
            search_url,
            params=params,
            wait_selector=source.wait_selector or "[data-test='JobCard'], a[data-test='job-title']",
        )
        return self._parse_listing(result.html, source=source, search_url=result.final_url, base=base)

    def _parse_listing(self, html: str, *, source: BoardSource, search_url: str, base: str) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobCandidate] = []
        cards = soup.select("[data-test='JobCard'], .job-card, article")
        for card in cards:
            title_el = card.select_one("[data-test='job-title'], h2 a, h3 a")
            company_el = card.select_one("[data-test='company-name'], .company")
            location_el = card.select_one("[data-test='location'], .location")
            link_el = card.select_one("a[href*='/jobs/'], a[href*='/l/']")
            title = title_el.get_text(" ", strip=True) if title_el else None
            company = company_el.get_text(" ", strip=True) if company_el else "Unknown employer"
            location_text = location_el.get_text(" ", strip=True) if location_el else None
            url = absolute_url(base, (link_el or title_el).get("href") if (link_el or title_el) else None)
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


class PlaywrightNeurotechAdapter:
    source_id = "neurotech"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
        browser: PlaywrightBrowserClient | None = None,
    ) -> list[JobCandidate]:
        del client, max_pages, location
        pw = _require_browser(browser)
        base = source.base_url.rstrip("/")
        result = pw.get_page_html(base, wait_selector=source.wait_selector or "a[href*='job'], .job-card")
        return self._parse_listing(result.html, source=source, search_url=result.final_url, base=base, query=query)

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
        for card in soup.select("div.job, article, .job-card, a[href*='job']"):
            title_el = card if card.name == "a" else card.select_one("h2 a, h3 a, a")
            if title_el is None:
                continue
            title = title_el.get_text(" ", strip=True)
            if not title or (query_lower not in title.lower() and query_lower not in card.get_text().lower()):
                continue
            company_el = card.select_one(".company, .employer")
            company = company_el.get_text(" ", strip=True) if company_el else "Unknown employer"
            url = absolute_url(base, title_el.get("href"))
            candidate = build_candidate(
                source=source,
                company_name=company,
                title=title,
                location=None,
                url=url,
                search_url=search_url,
            )
            if candidate is not None:
                results.append(candidate)
        return results


class PlaywrightLinkedInAdapter:
    source_id = "linkedin"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
        browser: PlaywrightBrowserClient | None = None,
    ) -> list[JobCandidate]:
        del client
        pw = _require_browser(browser)
        candidates: list[JobCandidate] = []
        base = source.base_url.rstrip("/")

        for page in range(max_pages):
            params = {
                "keywords": query,
                "location": location,
                "start": str(page * 25),
            }
            search_url = f"{base}/search"
            result = pw.get_page_html(
                search_url,
                params=params,
                wait_selector=source.wait_selector or ".base-card, .jobs-search__results-list li",
            )
            page_candidates = self._parse_listing(result.html, source=source, search_url=result.final_url)
            if not page_candidates:
                break
            candidates.extend(page_candidates)
        return candidates

    def _parse_listing(self, html: str, *, source: BoardSource, search_url: str) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobCandidate] = []
        for card in soup.select("div.base-card, li.jobs-search-results__list-item, .job-search-card"):
            title_el = card.select_one(".base-search-card__title, h3, .job-card-list__title")
            company_el = card.select_one(".base-search-card__subtitle, h4, .job-card-container__company-name")
            location_el = card.select_one(".job-search-card__location, .job-card-container__metadata-item")
            link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
            title = title_el.get_text(" ", strip=True) if title_el else None
            company = company_el.get_text(" ", strip=True) if company_el else "Unknown employer"
            location_text = location_el.get_text(" ", strip=True) if location_el else None
            url = link_el.get("href") if link_el else None
            if url and not url.startswith("http"):
                url = f"https://www.linkedin.com{url}"
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


PLAYWRIGHT_ADAPTERS = {
    "indeed_ca": PlaywrightIndeedCaAdapter(),
    "eluta": PlaywrightElutaAdapter(),
    "wellfound": PlaywrightWellfoundAdapter(),
    "neurotech": PlaywrightNeurotechAdapter(),
    "linkedin": PlaywrightLinkedInAdapter(),
}
