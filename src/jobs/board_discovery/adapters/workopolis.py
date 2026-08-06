"""Workopolis Canada adapter."""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate


class WorkopolisAdapter:
    source_id = "workopolis"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
        browser=None,
    ) -> list[JobCandidate]:
        del browser
        results: list[JobCandidate] = []
        base = source.base_url.rstrip("/")
        search_url = f"{base}{source.search_path or '/search'}"
        resolved_location = source.search_params.get("l", location)
        for page in range(1, max_pages + 1):
            params = {"q": query, "l": resolved_location, "pn": str(page)}
            try:
                html = client.get(search_url, params=params)
            except Exception:
                break
            page_results = self._parse_listing(
                html, source=source, search_url=search_url, base=base
            )
            if not page_results:
                break
            results.extend(page_results)
        return results

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
        base: str,
    ) -> list[JobCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        structured = self._parse_structured_data(
            soup, source=source, search_url=search_url, base=base
        )
        if structured:
            return structured

        results: list[JobCandidate] = []
        seen: set[str] = set()
        selectors = (
            "a[data-testid='job-title'], a[data-testid='search-result-title'], "
            "h2 a[href*='/job/'], h2 a[href*='/viewjob'], h3 a[href*='/job/'], "
            "a[href*='/job-listing/']"
        )
        for link in soup.select(selectors):
            href = absolute_url(base, link.get("href"))
            title = link.get_text(" ", strip=True)
            if not href or href in seen or not title:
                continue
            seen.add(href)
            card = link.find_parent(["article", "li"]) or link.parent
            company, location = self._company_and_location(card)
            candidate = build_candidate(
                source=source,
                company_name=company,
                title=title,
                location=location,
                url=href,
                search_url=search_url,
            )
            if candidate is not None:
                results.append(candidate)
        return results

    @staticmethod
    def _company_and_location(card: Tag | None) -> tuple[str, str | None]:
        if card is None:
            return "Unknown employer", None
        company_el = card.select_one(
            "[data-testid='company-name'], [class*='company'], [class*='employer']"
        )
        location_el = card.select_one(
            "[data-testid='job-location'], [class*='location']"
        )
        company = company_el.get_text(" ", strip=True) if company_el else ""
        location = location_el.get_text(" ", strip=True) if location_el else None
        if not company:
            text = card.get_text(" ", strip=True)
            match = re.search(r"\b([^—|]{2,80})\s+—\s+([^|]{2,80})", text)
            if match:
                company, location = match.group(1).strip(), match.group(2).strip()
        return company or "Unknown employer", location

    def _parse_structured_data(
        self,
        soup: BeautifulSoup,
        *,
        source: BoardSource,
        search_url: str,
        base: str,
    ) -> list[JobCandidate]:
        results: list[JobCandidate] = []
        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            for job in _walk_job_postings(payload):
                organization = job.get("hiringOrganization") or {}
                location = job.get("jobLocation") or {}
                address = location.get("address") if isinstance(location, dict) else {}
                if not isinstance(address, dict):
                    address = {}
                location_text = ", ".join(
                    str(address.get(key)).strip()
                    for key in ("addressLocality", "addressRegion", "addressCountry")
                    if address.get(key)
                ) or None
                candidate = build_candidate(
                    source=source,
                    company_name=str(organization.get("name") or "Unknown employer"),
                    title=str(job.get("title") or ""),
                    location=location_text,
                    url=absolute_url(base, job.get("url")),
                    description=BeautifulSoup(
                        str(job.get("description") or ""), "html.parser"
                    ).get_text("\n", strip=True) or None,
                    search_url=search_url,
                )
                if candidate is not None:
                    results.append(candidate)
        return results


def _walk_job_postings(value: Any):
    if isinstance(value, dict):
        if value.get("@type") == "JobPosting":
            yield value
        for child in value.values():
            yield from _walk_job_postings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_job_postings(child)
