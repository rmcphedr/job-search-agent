"""Digital Health Canada careers page adapter."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate

DEFAULT_CAREERS_PATH = "/careers/"


def _split_title_company(link_text: str, full_heading: str) -> tuple[str, str]:
    """Parse 'Title, Company' or plain title from careers list heading."""
    heading = full_heading.strip() or link_text.strip()
    if "," in heading:
        title, company = heading.rsplit(",", 1)
        return title.strip(), company.strip()
    return link_text.strip(), "Unknown employer"


def parse_digital_health_canada_listing(
    html: str,
    *,
    source: BoardSource,
    search_url: str,
    query: str = "",
) -> list[JobCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[JobCandidate] = []
    seen_urls: set[str] = set()
    base = source.base_url.rstrip("/")

    for block in soup.select(".job-content"):
        title_el = block.select_one("h4 a")
        if title_el is None:
            continue

        link_text = title_el.get_text(" ", strip=True)
        full_heading = block.select_one("h4")
        heading_text = full_heading.get_text(" ", strip=True) if full_heading else link_text
        url = absolute_url(base, title_el.get("href"))
        if not link_text or not url or url in seen_urls:
            continue

        title, company = _split_title_company(link_text, heading_text)

        location_text: str | None = None
        meta_el = block.select_one(".meta")
        if meta_el:
            location_text = re.sub(r"</?p>", "", meta_el.decode_contents(), flags=re.I).strip()
            location_text = BeautifulSoup(location_text, "html.parser").get_text(" ", strip=True)

        seen_urls.add(url)
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


class DigitalHealthCanadaAdapter:
    source_id = "digital_health_canada"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        del location, max_pages
        base = source.base_url.rstrip("/")
        careers_path = source.search_path or DEFAULT_CAREERS_PATH
        listing_url = f"{base}{careers_path}"

        try:
            html, final_url = client.get_with_url(listing_url)
        except Exception:
            return []

        return parse_digital_health_canada_listing(
            html,
            source=source,
            search_url=final_url,
            query="",
        )

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
        query: str = "",
    ) -> list[JobCandidate]:
        return parse_digital_health_canada_listing(
            html,
            source=source,
            search_url=search_url,
            query=query,
        )
