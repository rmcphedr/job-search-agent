"""Shared helpers for listing-page board adapters."""

from __future__ import annotations

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.parsers import build_candidate
from src.jobs.job_models import JobCandidate

CANADA_LOCATION_MARKERS = (
    "canada",
    ", on",
    ", qc",
    ", bc",
    ", ab",
    ", mb",
    ", sk",
    ", ns",
    ", nb",
    ", nl",
    ", pe",
    ", nt",
    ", nu",
    ", yt",
    "toronto",
    "montreal",
    "vancouver",
    "calgary",
    "edmonton",
    "ottawa",
    "winnipeg",
    "quebec",
    "british columbia",
    "ontario",
)


def matches_query(text: str, query: str) -> bool:
    query_lower = query.lower().strip()
    if not query_lower:
        return True
    blob = text.lower()
    if query_lower in blob:
        return True
    return any(part in blob for part in query_lower.split() if len(part) > 2)


def matches_canada_location(location: str | None) -> bool:
    if not location or not str(location).strip():
        return False
    normalized = location.lower()
    return any(marker in normalized for marker in CANADA_LOCATION_MARKERS)


def filter_listing_candidates(
    candidates: list[JobCandidate],
    *,
    query: str,
    require_canada: bool,
) -> list[JobCandidate]:
    filtered: list[JobCandidate] = []
    for candidate in candidates:
        blob = " ".join(
            part
            for part in (candidate.title, candidate.location or "", candidate.description or "")
            if part
        )
        if not matches_query(blob, query):
            continue
        if require_canada and not matches_canada_location(candidate.location):
            continue
        filtered.append(candidate)
    return filtered


def make_listing_candidate(
    *,
    source: BoardSource,
    company_name: str,
    title: str,
    location: str | None,
    url: str | None,
    search_url: str,
    description: str | None = None,
) -> JobCandidate | None:
    return build_candidate(
        source=source,
        company_name=company_name,
        title=title,
        location=location,
        url=url,
        description=description,
        search_url=search_url,
    )
