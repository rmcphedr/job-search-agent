"""URL and text utilities for job extraction."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

from src.discovery.link_utils import clean_url, normalize_url

PROVIDER_DOMAIN_MAP = {
    "greenhouse": ("greenhouse.io", "job-boards.greenhouse.io"),
    "lever": ("jobs.lever.co", "lever.co"),
    "ashby": ("jobs.ashbyhq.com", "ashbyhq.com"),
    "workable": ("workable.com", "apply.workable.com"),
    "bamboohr": ("bamboohr.com",),
    "smartrecruiters": ("jobs.smartrecruiters.com", "smartrecruiters.com"),
    "workday": ("myworkdayjobs.com", "workdayjobs.com"),
    "icims": ("icims.com",),
    "recruitee": ("recruitee.com",),
    "teamtailor": ("teamtailor.com",),
    "comeet": ("comeet.com", "comeet.co"),
    "personio": ("personio.de", "personio.com"),
}

JOB_LINK_TERMS = (
    "job",
    "jobs",
    "career",
    "careers",
    "opening",
    "openings",
    "position",
    "positions",
    "role",
    "roles",
    "apply",
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "bamboohr",
)

GENERIC_JOB_TITLE_BLOCKLIST = (
    "careers",
    "jobs",
    "job openings",
    "open positions",
    "view all",
    "apply now",
    "learn more",
)

GENERIC_ANCHOR_TEXTS = (
    "learn more",
    "apply now",
    "apply",
    "view job",
    "view role",
    "view position",
    "read more",
    "see more",
    "details",
    "more info",
)

INDIVIDUAL_JOB_URL_PATTERNS = (
    r"/jobs/\d",
    r"/jobs/[^/?#]+",
    r"/job/[^/?#]+",
    r"/careers-post/[^/?#]+",
    r"/career/[^/?#]+",
    r"/positions?/[^/?#]+",
    r"/openings?/[^/?#]+",
    r"/roles?/[^/?#]+",
    r"/opportunities/[^/?#]+",
    r"/vacancy/[^/?#]+",
    r"/posting/[^/?#]+",
)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_job_url(url: str | None) -> str | None:
    cleaned = clean_url(url)
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    normalized = parsed._replace(fragment="")
    return normalized.geturl().rstrip("/")


def get_domain(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def is_valid_http_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def detect_provider_from_url(url: str) -> str | None:
    lower_url = url.lower()
    for provider, fragments in PROVIDER_DOMAIN_MAP.items():
        if any(fragment in lower_url for fragment in fragments):
            return provider
    return None


def detect_provider_from_html(html: str) -> str | None:
    lower_html = html.lower()
    checks = (
        ("greenhouse", ("greenhouse.io", "boards.greenhouse.io")),
        ("lever", ("jobs.lever.co", "lever.co")),
        ("ashby", ("jobs.ashbyhq.com", "ashbyhq.com")),
        ("workable", ("workable.com", "apply.workable.com")),
        ("bamboohr", ("bamboohr.com/careers",)),
        ("smartrecruiters", ("jobs.smartrecruiters.com",)),
        ("workday", ("myworkdayjobs.com", "workdayjobs.com")),
        ("icims", ("icims.com",)),
        ("recruitee", ("recruitee.com",)),
        ("teamtailor", ("teamtailor.com",)),
        ("comeet", ("comeet.com", "comeet.co")),
        ("personio", ("personio.de", "personio.com")),
    )
    for provider, fragments in checks:
        if any(fragment in lower_html for fragment in fragments):
            return provider
    return None


def looks_like_job_link(text: str, href: str) -> bool:
    combined = normalize_text(f"{text} {href}")
    if not combined:
        return False
    if any(term in combined for term in ("privacy", "terms", "cookie", "linkedin.com/in")):
        return False
    return any(term in combined for term in JOB_LINK_TERMS)


def looks_like_job_title(text: str | None) -> bool:
    cleaned = normalize_text(text)
    if not cleaned or len(cleaned) < 3 or len(cleaned) > 180:
        return False
    if cleaned in GENERIC_JOB_TITLE_BLOCKLIST:
        return False
    return True


def is_generic_anchor_text(text: str | None) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return True
    return cleaned in GENERIC_ANCHOR_TEXTS or cleaned in GENERIC_JOB_TITLE_BLOCKLIST


def looks_like_individual_job_url(url: str | None) -> bool:
    if not url:
        return False
    lower_url = url.lower()
    return any(re.search(pattern, lower_url) for pattern in INDIVIDUAL_JOB_URL_PATTERNS)


def title_from_job_url(url: str | None) -> str | None:
    if not url or not looks_like_individual_job_url(url):
        return None
    slug = url.rstrip("/").split("/")[-1]
    if not slug or slug.isdigit():
        return None
    title = slug.replace("-", " ").replace("_", " ")
    title = re.sub(r"\s+", " ", title).strip()
    return title if looks_like_job_title(title) else None


def title_from_card_text(text: str | None) -> str | None:
    """Extract a job title from nearby card/listing text when anchor text is generic."""
    if not text:
        return None

    cleaned = re.sub(
        r"\s*(?:Learn More|Apply Now|View Job|View Role|Read More)\s*",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None

    explicit_locations = (
        r"\s+(?:TORONTO|CAIRO|REMOTE|HYBRID|VANCOUVER|MONTREAL|"
        r"SAN[\s\u00a0]FRANCISCO|CO-OP|ON-SITE|ONSITE)\b"
    )
    match = re.match(rf"^(?P<title>.+?){explicit_locations}", cleaned)
    if match:
        title = match.group("title").strip(" ,-|")
        if looks_like_job_title(title):
            return title

    all_caps_location = r"\s+(?:[A-Z]{2,}(?:\s+[A-Z/]{2,})+)\b"
    match = re.match(rf"^(?P<title>.+?){all_caps_location}", cleaned)
    if match:
        title = match.group("title").strip(" ,-|")
        if looks_like_job_title(title):
            return title

    description_starts = (
        r"\s+(?:We're|We are|Oncoustics|The |As a |As the |Our team|"
        r"This role|In this role|You will|You'll)\b"
    )
    parts = re.split(description_starts, cleaned, maxsplit=1, flags=re.IGNORECASE)
    if parts:
        title = parts[0].strip(" ,-|")
        if looks_like_job_title(title):
            return title

    return None


def is_career_listing_url(url: str | None, career_page: str | None = None) -> bool:
    """Return True when a URL points at a general careers listing, not an individual posting."""
    if not url:
        return False
    normalized = normalize_job_url(url) or url
    if career_page and normalize_job_url(career_page) == normalized:
        return True
    lower = normalized.lower()
    if looks_like_individual_job_url(normalized):
        return False
    listing_patterns = (
        r"/careers/?$",
        r"/careers/\d+/?$",
        r"/jobs/?$",
        r"/join-us/?$",
        r"/work-with-us/?$",
    )
    return any(re.search(pattern, lower) for pattern in listing_patterns)


def absolute_url(base_url: str, href: str) -> str | None:
    return normalize_url(base_url, href)


def compute_content_hash(title: str, description: str | None, url: str | None) -> str:
    payload = "|".join(
        [
            normalize_text(title),
            normalize_text(description or ""),
            normalize_job_url(url) or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def truncate_text(text: str | None, max_chars: int = 8000) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text.strip())
    return cleaned[:max_chars]
