"""BioTalent Canada – The PetriDish job board adapter."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.listing_utils import matches_query
from src.jobs.board_discovery.parsers import absolute_url, build_candidate
from src.jobs.job_models import JobCandidate

LISTING_PATH = "/the-petridish/"


def _split_title_company(link_text: str) -> tuple[str, str]:
    """Parse 'Job Title - Employer Inc.' into title and company."""
    text = link_text.strip()
    if " - " in text:
        title, company = text.rsplit(" - ", 1)
        return title.strip(), company.strip()
    return text, "Unknown employer"


def parse_petridish_listing(
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

    for article in soup.select("article.listing-entry, article.type-bio_job_posting"):
        title_el = article.select_one("h3.content-info-card-container-title a, h3 a")
        if title_el is None:
            continue

        link_text = title_el.get_text(" ", strip=True)
        url = absolute_url(base, title_el.get("href"))
        if not link_text or not url or url in seen_urls:
            continue

        title, company = _split_title_company(link_text)
        if query and not matches_query(f"{title} {company}", query):
            continue

        location_el = article.select_one(".content-info-card-container-subheader, .content-info-card-subheader")
        location_text = location_el.get_text(" ", strip=True) if location_el else None

        # Prefer employer name from logo link domain when title lacks " - Company".
        if company == "Unknown employer":
            logo_link = article.select_one(".content-info-card-logo-container a[href]")
            if logo_link and logo_link.get("href", "").startswith("http"):
                host = logo_link["href"].split("//", 1)[-1].split("/")[0]
                company = host.replace("www.", "")

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


def _page_url(base: str, page: int) -> str:
    if page <= 1:
        return f"{base}{LISTING_PATH}"
    return f"{base}{LISTING_PATH}page/{page}/"


class PetridishAdapter:
    source_id = "petridish"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        del location
        candidates: list[JobCandidate] = []
        base = source.base_url.rstrip("/")

        for page in range(1, max_pages + 1):
            listing_url = _page_url(base, page)
            try:
                html, final_url = client.get_with_url(listing_url)
            except Exception:
                break

            page_candidates = parse_petridish_listing(
                html,
                source=source,
                search_url=final_url,
                query=query,
            )
            if not _has_listing_articles(html):
                break
            candidates.extend(page_candidates)

        return candidates

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
        query: str = "",
    ) -> list[JobCandidate]:
        return parse_petridish_listing(html, source=source, search_url=search_url, query=query)


def _has_listing_articles(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(soup.select("article.listing-entry, article.type-bio_job_posting"))
