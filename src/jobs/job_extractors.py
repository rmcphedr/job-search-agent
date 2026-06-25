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
from src.jobs.job_detail_parsers import fix_text_encoding, parse_job_detail_from_html
from src.jobs.discovery_config import DiscoveryConfig, load_discovery_config
from src.jobs.filter_jobs import prescreen_jobs, score_job, apply_location_score_boost
from src.jobs.job_models import JobCandidate
from src.jobs.search_strategies import (
    ABBVIE_PORTAL,
    build_abbvie_search_queries,
    build_abbvie_search_url,
    build_search_targets,
    dedupe_job_candidates,
    detect_search_strategy,
)
from src.jobs.job_url_utils import (
    absolute_url,
    compute_content_hash,
    detect_provider_from_html,
    detect_provider_from_url,
    is_generic_anchor_text,
    is_career_listing_url,
    is_work_location_type,
    location_from_job_url,
    looks_like_individual_job_url,
    looks_like_job_link,
    looks_like_job_portal_link,
    looks_like_job_title,
    normalize_job_url,
    title_from_card_text,
    title_from_job_url,
    truncate_text,
)
from src.llm.job_description import format_job_description_safe
from src.llm.job_triage import triage_jobs

logger = logging.getLogger(__name__)

MAX_PAGE_CHARS = 100_000
MAX_DETAIL_FETCHES = 25
MAX_JOB_PORTAL_HOPS = 2


def fetch_page(url: str) -> tuple[int, str, str]:
    """Fetch a URL and return status code, final URL, and HTML text."""
    headers = {"User-Agent": get_user_agent()}
    timeout = get_request_timeout()
    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
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
    from src.jobs.job_url_utils import is_work_location_type, location_from_job_url

    geography = None
    patterns = (
        r"(?:location|office|city)\s*[:\-]\s*([^\n|]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate and not is_work_location_type(candidate):
                geography = candidate
                break

    if geography:
        return geography

    work_type_match = re.search(r"\b(remote|hybrid|on-site|onsite)\b", text, flags=re.IGNORECASE)
    if work_type_match and not geography:
        return None

    return None


def extract_job_detail(
    url: str,
    *,
    company_name: str = "",
    format_description: bool = True,
) -> dict[str, str | None]:
    """Fetch and parse an individual job detail page."""
    status_code, final_url, html = fetch_page(url)
    if status_code not in {200, 301, 302} or not html:
        return {
            "title": None,
            "location": None,
            "location_type": None,
            "description": None,
            "url": normalize_job_url(final_url),
        }

    parsed = parse_job_detail_from_html(html, final_url)
    title = parsed["title"]
    if not title or not looks_like_job_title(title):
        soup = BeautifulSoup(html, "html.parser")
        for selector in ("h1", "h2", "title"):
            element = soup.find(selector)
            if element:
                candidate = element.get_text(" ", strip=True)
                if looks_like_job_title(candidate):
                    title = candidate
                    break

    location = parsed["location"] or location_from_job_url(final_url)
    if is_work_location_type(location):
        location = location_from_job_url(final_url)

    description = parsed["description_raw"]
    if format_description and description:
        formatted, _error = format_job_description_safe(
            company_name=company_name,
            title=title or "",
            location=location,
            location_type=parsed["location_type"],
            raw_description=description,
        )
        description = formatted or description

    return {
        "title": fix_text_encoding(title),
        "location": location,
        "location_type": parsed["location_type"],
        "description": truncate_text(description),
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
        location = location_from_job_url(job_url)
        parent = anchor.parent if isinstance(anchor.parent, Tag) else None
        if parent is not None and not location:
            location = _extract_location_from_text(parent.get_text(" ", strip=True))
            if is_work_location_type(location):
                location = location_from_job_url(job_url)
            if not title:
                for sibling in parent.find_all("a", href=True):
                    sibling_text = sibling.get_text(" ", strip=True)
                    if (
                        sibling is not anchor
                        and looks_like_job_title(sibling_text)
                        and not is_generic_anchor_text(sibling_text)
                    ):
                        title = sibling_text
                        break

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
        r"boards-api\.greenhouse\.io/v1/boards/([^/?#\"'\s]+)",
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


def _needs_detail_enrichment(candidate: JobCandidate) -> bool:
    if not candidate.url:
        return False
    if not candidate.description or len(candidate.description) <= 120:
        return True
    if is_work_location_type(candidate.location):
        return True
    return False


def enrich_job_details(
    candidates: list[JobCandidate],
    *,
    max_fetches: int = MAX_DETAIL_FETCHES,
    company_name: str = "",
    format_description: bool = True,
) -> list[JobCandidate]:
    """Fetch individual job pages to enrich title, location, and description."""
    enriched: list[JobCandidate] = []
    fetches = 0
    for candidate in candidates:
        if not _needs_detail_enrichment(candidate):
            enriched.append(candidate)
            continue
        if fetches >= max_fetches:
            enriched.append(candidate)
            continue
        detail = extract_job_detail(
            candidate.url or "",
            company_name=company_name or candidate.company_name,
            format_description=format_description,
        )
        fetches += 1
        location = detail["location"] or candidate.location
        if is_work_location_type(location):
            location = detail["location"] or location_from_job_url(detail["url"] or candidate.url)
        enriched.append(
            candidate.model_copy(
                update={
                    "title": detail["title"] or candidate.title,
                    "location": location,
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


def _looks_like_real_job(candidate: JobCandidate) -> bool:
    if not candidate.title:
        return False
    title = candidate.title.lower()
    nav_terms = (
        "search jobs",
        "search postings",
        "job alerts",
        "all jobs",
        "view all",
        "learn more",
        "how to apply",
        "frequently asked",
        "positions and views",
        "explore careers",
        "around the world",
        "equality, diversity",
        "follow us",
        "position category",
        "bookmark",
        "after you apply",
        "workplace & career",
        "apply to a program",
    )
    return not any(term in title for term in nav_terms)


def _collect_portal_targets(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href"))
        text = anchor.get_text(" ", strip=True)
        if not looks_like_job_portal_link(text, href):
            continue
        absolute = absolute_url(base_url, href)
        if not absolute or absolute.rstrip("/") in seen:
            continue
        if looks_like_individual_job_url(absolute):
            continue
        seen.add(absolute.rstrip("/"))
        targets.append((absolute, text))
    return targets


def _follow_job_portals(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
    provider: str,
    extractor: Callable[..., list[JobCandidate]],
    hops_remaining: int = MAX_JOB_PORTAL_HOPS,
) -> list[JobCandidate]:
    """Follow hub links (e.g. 'Current Job Openings') when the landing page has no jobs."""
    if hops_remaining <= 0:
        return []

    for portal_url, _anchor_text in _collect_portal_targets(html, url):
        status_code, final_url, portal_html = fetch_page(portal_url)
        if status_code not in {200, 301, 302} or not portal_html:
            continue

        portal_provider = detect_career_provider(final_url, portal_html)
        portal_extractor = PROVIDER_EXTRACTORS.get(portal_provider, extractor)
        jobs = portal_extractor(
            final_url,
            portal_html,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
        )
        real_jobs = [job for job in jobs if _looks_like_real_job(job)]
        if real_jobs:
            return real_jobs

        nested = _follow_job_portals(
            final_url,
            portal_html,
            company_name=company_name,
            company_id=company_id,
            source_career_page=source_career_page,
            provider=portal_provider,
            extractor=portal_extractor,
            hops_remaining=hops_remaining - 1,
        )
        if nested:
            return nested

    return []


def _extract_listings_from_page(
    url: str,
    html: str,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
    provider: str,
    extractor: Callable[..., list[JobCandidate]],
) -> list[JobCandidate]:
    """Extract job listing metadata from a single page without detail enrichment."""
    jobs = extractor(
        url,
        html,
        company_name=company_name,
        company_id=company_id,
        source_career_page=source_career_page,
    )
    real_jobs = [job for job in jobs if _looks_like_real_job(job)]
    if real_jobs:
        return real_jobs

    return _follow_job_portals(
        url,
        html,
        company_name=company_name,
        company_id=company_id,
        source_career_page=source_career_page,
        provider=provider,
        extractor=extractor,
    )


def _harvest_from_search_targets(
    targets: list,
    *,
    company_name: str,
    company_id: int | None,
    source_career_page: str,
    provider: str,
    extractor: Callable[..., list[JobCandidate]],
    discovery_config: DiscoveryConfig,
) -> tuple[list[JobCandidate], int]:
    """Harvest listing metadata from search portals with per-query pagination."""
    collected: list[JobCandidate] = []
    pages_fetched = 0
    max_listings = discovery_config.budgets.max_listings_per_company
    max_pages = discovery_config.budgets.max_listing_pages_per_query

    for target in targets:
        if len(collected) >= max_listings:
            break

        if target.label.startswith("abbvie:"):
            queries = build_abbvie_search_queries(discovery_config)
            for query in queries:
                if len(collected) >= max_listings:
                    break
                for page in range(1, max_pages + 1):
                    search_url = build_abbvie_search_url(target.url, query, page)
                    status_code, final_url, html = fetch_page(search_url)
                    pages_fetched += 1
                    if status_code not in {200, 301, 302} or not html:
                        break

                    page_jobs = _extract_listings_from_page(
                        final_url,
                        html,
                        company_name=company_name,
                        company_id=company_id,
                        source_career_page=source_career_page,
                        provider=provider,
                        extractor=extractor,
                    )
                    if not page_jobs:
                        break

                    before = len(collected)
                    collected.extend(page_jobs)
                    collected = dedupe_job_candidates(collected)
                    if len(collected) == before:
                        break
                    if len(collected) >= max_listings:
                        collected = collected[:max_listings]
                        break

    return collected, pages_fetched


def _apply_prescreen_and_enrich(
    jobs: list[JobCandidate],
    *,
    company_name: str,
    discovery_config: DiscoveryConfig,
    enrich_details: bool,
) -> tuple[list[JobCandidate], int, int, int, int]:
    """Pre-screen, LLM-triage, then enrich only triage survivors."""
    raw_count = len(jobs)
    jobs = dedupe_job_candidates(jobs)
    jobs = [job for job in jobs if _looks_like_real_job(job)]

    prescreened = prescreen_jobs(
        jobs,
        min_keyword_score=discovery_config.prescreen.min_keyword_score,
        title_only=discovery_config.prescreen.title_only,
        location_filters=discovery_config.location_filters,
        require_location_match=discovery_config.prescreen.require_location_match,
        location_score_boost=discovery_config.prescreen.location_score_boost,
    )
    prescreened = prescreened[: discovery_config.budgets.max_jobs_saved_per_company]

    triaged, triaged_count = triage_jobs(
        prescreened,
        enabled=discovery_config.llm_triage.enabled,
        min_triage_score=discovery_config.llm_triage.min_triage_score,
        max_calls=discovery_config.budgets.max_llm_triage_calls,
        fallback_to_keywords=discovery_config.llm_triage.fallback_to_keywords,
    )

    if not enrich_details or not triaged:
        return triaged, raw_count, len(prescreened), triaged_count, 0

    enrich_limit = discovery_config.budgets.max_detail_fetches
    to_enrich = triaged[:enrich_limit]
    enriched = enrich_job_details(
        to_enrich,
        max_fetches=enrich_limit,
        company_name=company_name,
        format_description=discovery_config.prescreen.format_descriptions,
    )

    enriched_by_url = {job.url: job for job in enriched if job.url}
    enriched_count = sum(
        1
        for job in enriched_by_url.values()
        if job.description and len(job.description) > 120
    )
    final_jobs: list[JobCandidate] = []
    keywords = None
    for job in triaged:
        enriched_job = enriched_by_url.get(job.url)
        if enriched_job is not None:
            score, matched = score_job(enriched_job, keywords, title_only=False)
            score = apply_location_score_boost(
                score,
                location=enriched_job.location,
                location_filters=discovery_config.location_filters,
                boost=discovery_config.prescreen.location_score_boost,
            )
            final_jobs.append(
                enriched_job.model_copy(
                    update={
                        "keyword_score": score,
                        "matched_keywords": matched,
                        "triage_score": job.triage_score,
                        "notes": job.notes,
                    }
                )
            )
        else:
            final_jobs.append(job)

    return final_jobs, raw_count, len(prescreened), triaged_count, enriched_count


def extract_jobs_from_career_page(
    career_page: str,
    *,
    company_name: str,
    company_id: int | None = None,
    enrich_details: bool = True,
    discovery_config: DiscoveryConfig | None = None,
) -> dict[str, object]:
    """
    Fetch a career page, detect provider, and extract job candidates.

    Returns status metadata and a list of JobCandidate objects.
    """
    config = discovery_config or load_discovery_config()
    normalized_page = normalize_url(career_page, career_page) or clean_url_fallback(career_page)
    if not normalized_page:
        return {
            "status": "ERROR",
            "provider": None,
            "final_url": career_page,
            "page_title": "",
            "jobs": [],
            "raw_jobs_found": 0,
            "prescreened_jobs": 0,
            "triaged_jobs": 0,
            "enriched_jobs": 0,
            "search_strategy": None,
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
            "raw_jobs_found": 0,
            "prescreened_jobs": 0,
            "triaged_jobs": 0,
            "enriched_jobs": 0,
            "search_strategy": None,
            "notes": f"Failed to fetch career page (status={status_code})",
        }

    provider = detect_career_provider(final_url, html)
    extractor = PROVIDER_EXTRACTORS.get(provider, extract_generic_html_jobs)
    search_strategy = detect_search_strategy(final_url, html, provider)
    search_targets = build_search_targets(final_url, html, provider, config)
    pages_fetched = 1

    if search_targets:
        jobs, pages_fetched = _harvest_from_search_targets(
            search_targets,
            company_name=company_name,
            company_id=company_id,
            source_career_page=normalized_page,
            provider=provider,
            extractor=extractor,
            discovery_config=config,
        )
        notes_prefix = (
            f"Search-first harvest via {search_strategy}: "
            f"{pages_fetched} listing page(s), "
            f"{len(build_abbvie_search_queries(config))} queries"
            if search_strategy == ABBVIE_PORTAL
            else f"Search-first harvest via {search_strategy}: {pages_fetched} page(s)"
        )
    else:
        jobs = _extract_listings_from_page(
            final_url,
            html,
            company_name=company_name,
            company_id=company_id,
            source_career_page=normalized_page,
            provider=provider,
            extractor=extractor,
        )
        notes_prefix = f"Landing-page extraction via {provider}"

    final_jobs, raw_count, prescreened_count, triaged_count, enriched_count = (
        _apply_prescreen_and_enrich(
            jobs,
            company_name=company_name,
            discovery_config=config,
            enrich_details=enrich_details,
        )
    )

    return {
        "status": "OK",
        "provider": provider,
        "final_url": final_url,
        "page_title": _extract_page_title(html),
        "jobs": final_jobs,
        "raw_jobs_found": raw_count,
        "prescreened_jobs": prescreened_count,
        "triaged_jobs": triaged_count,
        "enriched_jobs": enriched_count,
        "search_strategy": search_strategy,
        "notes": (
            f"{notes_prefix}; {prescreened_count}/{raw_count} passed pre-screen; "
            f"{triaged_count} passed LLM triage; {enriched_count} enriched; "
            f"saved {len(final_jobs)}"
        ),
    }


def clean_url_fallback(value: str) -> str | None:
    from src.discovery.link_utils import clean_url

    return clean_url(value)
