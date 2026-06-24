"""Search-first listing strategies for large career portals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urljoin, urlparse

from src.jobs.discovery_config import DiscoveryConfig
from src.jobs.job_models import JobCandidate

ABBVIE_PORTAL = "abbvie_portal"
GREENHOUSE_API = "greenhouse_api"


@dataclass(frozen=True)
class SearchTarget:
    url: str
    label: str


def detect_search_strategy(career_page_url: str, html: str, provider: str) -> str | None:
    """Return a search strategy id when listings require query-based harvesting."""
    lower_url = career_page_url.lower()
    lower_html = html.lower()

    if "careers.abbvie.com" in lower_url or "/en/jobs?q=" in lower_html:
        return ABBVIE_PORTAL

    if provider == "greenhouse":
        return GREENHOUSE_API

    return None


def _abbvie_jobs_base(career_page_url: str) -> str:
    parsed = urlparse(career_page_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return urljoin(origin + "/", "en/jobs")


def build_abbvie_search_queries(config: DiscoveryConfig) -> list[str]:
    """Return keyword queries for the AbbVie careers portal."""
    return config.search_queries[: config.budgets.max_search_queries]


def build_abbvie_search_url(base_jobs_url: str, query: str, page: int) -> str:
    encoded = quote_plus(query)
    return f"{base_jobs_url}?q={encoded}&page={page}"


def build_search_targets(
    career_page_url: str,
    html: str,
    provider: str,
    config: DiscoveryConfig,
) -> list[SearchTarget]:
    """Return a marker target when search-first harvesting applies; empty list otherwise."""
    strategy = detect_search_strategy(career_page_url, html, provider)
    if strategy == ABBVIE_PORTAL:
        base = _abbvie_jobs_base(career_page_url)
        return [SearchTarget(url=base, label=f"abbvie:{strategy}")]
    return []


def job_dedupe_key(candidate: JobCandidate) -> str:
    """Stable dedupe key preferring ATS job ids embedded in URLs."""
    url = (candidate.url or "").lower()
    match = re.search(r"jid[-_/]?(\d+)", url)
    if match:
        return f"jid:{match.group(1)}"
    if candidate.content_hash:
        return candidate.content_hash
    return f"title:{candidate.title.lower()}|url:{url}"


def dedupe_job_candidates(candidates: list[JobCandidate]) -> list[JobCandidate]:
    """Dedupe jobs, keeping the best title when duplicates share the same job id."""
    best_by_key: dict[str, JobCandidate] = {}
    for candidate in candidates:
        key = job_dedupe_key(candidate)
        existing = best_by_key.get(key)
        if existing is None or _title_quality(candidate.title) > _title_quality(existing.title):
            best_by_key[key] = candidate
    return list(best_by_key.values())


def _title_quality(title: str) -> int:
    """Prefer properly cased titles over slug-like duplicates."""
    score = 0
    if title and title[0].isupper():
        score += 2
    if " jid " not in title.lower():
        score += 1
    if len(title) < 120:
        score += 1
    return score
