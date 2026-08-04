"""Shared parsing helpers for board adapters."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.job_models import JobCandidate


def absolute_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base_url.rstrip("/") + "/", href.lstrip("/"))


def first_text(element, selector: str) -> str | None:
    if element is None:
        return None
    found = element.select_one(selector)
    if found is None:
        return None
    text = found.get_text(" ", strip=True)
    return text or None


def first_link(element, selector: str, base_url: str) -> tuple[str | None, str | None]:
    if element is None:
        return None, None
    anchor = element.select_one(selector)
    if anchor is None:
        return None, None
    title = anchor.get_text(" ", strip=True) or None
    href = absolute_url(base_url, anchor.get("href"))
    return title, href


def build_candidate(
    *,
    source: BoardSource,
    company_name: str,
    title: str,
    location: str | None,
    url: str | None,
    description: str | None = None,
    search_url: str,
) -> JobCandidate | None:
    cleaned_title = (title or "").strip()
    cleaned_company = (company_name or "").strip()
    if not cleaned_title or not cleaned_company:
        return None
    return JobCandidate(
        company_name=cleaned_company,
        title=cleaned_title,
        location=location,
        url=url,
        description=description,
        provider=source.source_id,
        source_career_page=search_url,
    )


def parse_html_list_page(
    html: str,
    *,
    source: BoardSource,
    search_url: str,
) -> list[JobCandidate]:
    """Parse a listing page using CSS selectors from board config."""
    selectors = source.selectors
    if not selectors:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(selectors.get("item", "article"))
    candidates: list[JobCandidate] = []

    for item in items:
        title, url = first_link(item, selectors.get("link", "a"), source.base_url)
        if not title:
            title = first_text(item, selectors.get("title", "h2"))
        company = first_text(item, selectors.get("company", ".company"))
        location = first_text(item, selectors.get("location", ".location"))
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
            candidates.append(candidate)

    return candidates
