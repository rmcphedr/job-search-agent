"""Career page provider detection and job listing extraction."""

from __future__ import annotations

import json
import logging
import re
from typing import Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

from src.discovery.fetch import get_request_timeout, get_user_agent
from src.discovery.link_utils import clean_url, normalize_url
from src.jobs.job_models import JobCandidate
from src.jobs.job_url_utils import (
    absolute_url,
    compute_content_hash,
    detect_provider_from_html,
    detect_provider_from_url,
    is_generic_anchor_text,
    is_career_listing_url,
    looks_like_job_link,
    looks_like_job_title,
    normalize_job_url,
    title_from_card_text,
    title_from_job_url,
    truncate_text,
)

logger = logging.getLogger(__name__)

MAX_PAGE_CHARS = 100_000
MAX_DETAIL_FETCHES = 25


def fetch_page(url: str) -> tuple[int, str, str]:
    """Fetch a URL and return status code, final URL, and HTML text."""
    headers = {"User-Agent": get_user_agent()}
    timeout = get_request_timeout()
    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        html = response.text[:MAX_PAGE_CHARS] if response.text else ""
        return response.status_code, response.url, html
    except requests.RequestException as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return 0, url, ""


def detect_career_provider(url: str, html: str) -> str:
    """Detect the ATS/provider for a careers page."""
    provider = detect_provider_from_url(url)
    if provider:
        return provider
    provider = detect_provider_from_html(html)
    if provider:
        return provider
    return "generic_html"


def _extract_page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def _extract_location_from_text(text: str) -> str | None:
    patterns = (
        r"(?:location|office|workplace)\s*[:\-]\s*([^\n|]+)",
        r"\b(remote|hybrid|on-site|onsite)\b[^|\n]*",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1 if match.lastindex else 0).strip()
    return None


def extract_job_detail(url: str) -> dict[str, str | None]:
    """Fetch and parse an individual job detail page."""
    status_code, final_url, html = fetch_page(url)
    if status_code not in {200, 301, 302} or not html:
        return {
            "title": None,
            "location": None,
            "description": None,
            "url": normalize_job_url(final_url),
        }

    soup = BeautifulSoup(html, "html.parser")
    title = None
    for selector in ("h1", "h2", "title"):
        element = soup.find(selector)
        if element:
            candidate = element.get_text(" ", strip=True)
            if looks_like_job_title(candidate):
                title = candidate
                break

    location = None
    for label in soup.find_all(string=re.compile(r"location|office|remote|workplace", re.I)):
        parent = label.parent if isinstance(label, Tag) else None
        if parent is not None:
            location = _extract_location_from_text(parent.get_text(" ", strip=True))
            if location:
                break

    description = None
    for selector in (
        "main",
        "article",
        'div[class*="description"]',
        'div[class*="content"]',
        "body",
    ):
        block = soup.select_one(selector)
        if block is not None:
            description = truncate_text(block.get_text("\n", strip=True))
            if description and len(description) > 80:
                break

    return {
        "title": title,
        "location": location,
        "description": description,
        "url": normalize_job_url(final_url),
    }


def _make_candidate(
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
    provider: str,
    title: str,
    url: str | None = None,
    location: str | None = None,
    description: str | None = None,
    date_posted: str | None = None,
    notes: str | None = None,
) -> JobCandidate | None:
    if not looks_like_job_title(title):
        return None
    normalized_url = normalize_job_url(url)
    content_hash = compute_content_hash(title, description, normalized_url)
    return JobCandidate(
        company_name=company_name,
        company_id=company_id,
        title=title.strip(),
        location=location,
        url=normalized_url,
        description=truncate_text(description),
        date_posted=date_posted,
        provider=provider,
        source_career_page=source_career_page,
        content_hash=content_hash,
        notes=notes,
    )


def _dedupe_candidates(candidates: list[JobCandidate]) -> list[JobCandidate]:
    seen: set[str] = set()
    deduped: list[JobCandidate] = []
    for candidate in candidates:
        key = candidate.content_hash or compute_content_hash(
            candidate.title, candidate.description, candidate.url
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _extract_links_as_jobs(
    html: str,
    base_url: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
    provider: str,
    href_filter: Callable[[str, str], bool] | None = None,
) -> list[JobCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[JobCandidate] = []

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href"))
        text = anchor.get_text(" ", strip=True)
        if href_filter and not href_filter(text, href):
            continue
        if not href_filter and not looks_like_job_link(text, href):
            continue

        job_url = absolute_url(base_url, href)
        if not job_url:
            continue
        if is_career_listing_url(job_url, source_career_page):
            continue

        title = text if looks_like_job_title(text) and not is_generic_anchor_text(text) else None
        location = None
        parent = anchor.parent if isinstance(anchor.parent, Tag) else None
        if parent is not None:
            location = _extract_location_from_text(parent.get_text(" ", strip=True))

        if not title and parent is not None:
            title = title_from_card_text(parent.get_text(" ", strip=True))
            if not title:
                grandparent = parent.parent if isinstance(parent.parent, Tag) else None
                if grandparent is not None:
                    for heading in grandparent.find_all(["h1", "h2", "h3", "h4", "h5"], limit=3):
                        heading_text = heading.get_text(" ", strip=True)
                        if looks_like_job_title(heading_text):
                            title = heading_text
                            break

        if not title:
            title = title_from_job_url(job_url)

        if not title:
            continue

        candidate = _make_candidate(
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider=provider,
            title=title,
            url=job_url,
            location=location,
        )
        if candidate is not None:
            candidates.append(candidate)

    return candidates


def _greenhouse_board_token(url: str, html: str) -> str | None:
    skip_tokens = {"embed", "job_board", "js", "jobs", "v1", "boards"}
    patterns = (
        r"boards\.greenhouse\.io/([^/?#\"'\s]+)",
        r"job-boards\.greenhouse\.io/([^/?#\"'\s]+)",
        r"embed/job_board/js\?[^\"']*?\bfor=([^&\"'\s]+)",
        r"boards\.greenhouse\.io/embed/job_board/js\?[^\"']*?\bfor=([^&\"'\s]+)",
        r"data-board-token=[\"']([^\"']+)[\"']",
        r"boardToken[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']",
    )
    for source in (url, html):
        for pattern in patterns:
            match = re.search(pattern, source, flags=re.I)
            if not match:
                continue
            token = match.group(1).strip()
            if token and token.lower() not in skip_tokens:
                return token
    return None


def _html_to_text(html_content: str | None) -> str | None:
    if not html_content:
        return None
    soup = BeautifulSoup(html_content, "html.parser")
    return truncate_text(soup.get_text("\n", strip=True))


def extract_greenhouse_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    board = _greenhouse_board_token(url, html)
    if board:
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        try:
            response = requests.get(api_url, timeout=get_request_timeout())
            if response.status_code == 200:
                payload = response.json()
                jobs = payload.get("jobs", [])
                candidates: list[JobCandidate] = []
                for job in jobs:
                    title = str(job.get("title", "")).strip()
                    job_url = job.get("absolute_url")
                    location = None
                    location_obj = job.get("location")
                    if isinstance(location_obj, dict):
                        location = location_obj.get("name")
                    elif isinstance(location_obj, str):
                        location = location_obj
                    description = _html_to_text(str(job.get("content", "")))
                    candidate = _make_candidate(
                        company_name=company_name,
                        company_id=company_id,
                        source_career_page=source_career_page,
                        provider="greenhouse",
                        title=title,
                        url=str(job_url) if job_url else None,
                        location=location,
                        description=description,
                        notes="Greenhouse API",
                    )
                    if candidate is not None:
                        candidates.append(candidate)
                if candidates:
                    return _dedupe_candidates(candidates)
        except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Greenhouse API failed for %s: %s", board, exc)

    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="greenhouse",
            href_filter=lambda text, href: "greenhouse.io" in href.lower() and "/jobs" in href.lower(),
        )
    )


def extract_lever_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="lever",
            href_filter=lambda text, href: "jobs.lever.co" in href.lower() or "lever.co" in href.lower(),
        )
    )


def extract_ashby_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    jobs = _extract_links_as_jobs(
        html,
        url,
        company_name=company_name,
        company_id=company_id,
        source_career_page=source_career_page,
        provider="ashby",
        href_filter=lambda text, href: "ashbyhq.com" in href.lower() or "/job/" in href.lower(),
    )
    if not jobs:
        logger.info("Ashby page may be JS-rendered: %s", url)
    return _dedupe_candidates(jobs)


def extract_workable_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="workable",
            href_filter=lambda text, href: "workable.com" in href.lower(),
        )
    )


def extract_bamboohr_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="bamboohr",
            href_filter=lambda text, href: "bamboohr.com" in href.lower() or looks_like_job_link(text, href),
        )
    )


def extract_smartrecruiters_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="smartrecruiters",
            href_filter=lambda text, href: "smartrecruiters.com" in href.lower(),
        )
    )


def extract_workday_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    jobs = _extract_links_as_jobs(
        html,
        url,
        company_name=company_name,
        company_id=company_id,
        source_career_page=source_career_page,
        provider="workday",
        href_filter=lambda text, href: "workday" in href.lower() or looks_like_job_link(text, href),
    )
    if not jobs:
        logger.info("Workday page may be JS-rendered: %s", url)
    return _dedupe_candidates(jobs)


def extract_icims_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="icims",
            href_filter=lambda text, href: "icims.com" in href.lower() or looks_like_job_link(text, href),
        )
    )


def extract_recruitee_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="recruitee",
            href_filter=lambda text, href: "recruitee.com" in href.lower(),
        )
    )


def extract_teamtailor_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="teamtailor",
            href_filter=lambda text, href: "teamtailor.com" in href.lower(),
        )
    )


def extract_comeet_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="comeet",
            href_filter=lambda text, href: "comeet" in href.lower(),
        )
    )


def extract_personio_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="personio",
            href_filter=lambda text, href: "personio" in href.lower(),
        )
    )


def extract_generic_html_jobs(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
) -> list[JobCandidate]:
    return _dedupe_candidates(
        _extract_links_as_jobs(
            html,
            url,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider="generic_html",
        )
    )


PROVIDER_EXTRACTORS: dict[str, Callable[..., list[JobCandidate]]] = {
    "greenhouse": extract_greenhouse_jobs,
    "lever": extract_lever_jobs,
    "ashby": extract_ashby_jobs,
    "workable": extract_workable_jobs,
    "bamboohr": extract_bamboohr_jobs,
    "smartrecruiters": extract_smartrecruiters_jobs,
    "workday": extract_workday_jobs,
    "icims": extract_icims_jobs,
    "recruitee": extract_recruitee_jobs,
    "teamtailor": extract_teamtailor_jobs,
    "comeet": extract_comeet_jobs,
    "personio": extract_personio_jobs,
    "generic_html": extract_generic_html_jobs,
}


def enrich_job_details(candidates: list[JobCandidate], max_fetches: int = MAX_DETAIL_FETCHES) -> list[JobCandidate]:
    """Fetch individual job pages to enrich title, location, and description."""
    enriched: list[JobCandidate] = []
    fetches = 0
    for candidate in candidates:
        if not candidate.url or (candidate.description and len(candidate.description) > 120):
            enriched.append(candidate)
            continue
        if fetches >= max_fetches:
            enriched.append(candidate)
            continue
        detail = extract_job_detail(candidate.url)
        fetches += 1
        enriched.append(
            candidate.model_copy(
                update={
                    "title": detail["title"] or candidate.title,
                    "location": detail["location"] or candidate.location,
                    "description": detail["description"] or candidate.description,
                    "url": detail["url"] or candidate.url,
                    "content_hash": compute_content_hash(
                        detail["title"] or candidate.title,
                        detail["description"] or candidate.description,
                        detail["url"] or candidate.url,
                    ),
                }
            )
        )
    return enriched


def extract_jobs_from_career_page(
    career_page: str,
    *,
    company_name: str,
    company_id: int | None = None,
    enrich_details: bool = True,
) -> dict[str, object]:
    """
    Fetch a career page, detect provider, and extract job candidates.

    Returns status metadata and a list of JobCandidate objects.
    """
    normalized_page = normalize_url(career_page, career_page) or clean_url_fallback(career_page)
    if not normalized_page:
        return {
            "status": "ERROR",
            "provider": None,
            "final_url": career_page,
            "page_title": "",
            "jobs": [],
            "notes": "Invalid career page URL",
        }

    status_code, final_url, html = fetch_page(normalized_page)
    if status_code not in {200, 301, 302} or not html:
        return {
            "status": "ERROR",
            "provider": None,
            "final_url": final_url,
            "page_title": "",
            "jobs": [],
            "notes": f"Failed to fetch career page (status={status_code})",
        }

    provider = detect_career_provider(final_url, html)
    extractor = PROVIDER_EXTRACTORS.get(provider, extract_generic_html_jobs)
    jobs = extractor(
        final_url,
        html,
        company_name=company_name,
        company_id=company_id,
        source_career_page=normalized_page,
    )
    if enrich_details:
        jobs = enrich_job_details(jobs)

    return {
        "status": "OK",
        "provider": provider,
        "final_url": final_url,
        "page_title": _extract_page_title(html),
        "jobs": jobs,
        "notes": f"Extracted {len(jobs)} raw job candidate(s) via {provider}",
    }


def clean_url_fallback(value: str) -> str | None:
    from src.discovery.link_utils import clean_url

    return clean_url(value)
