"""Utilities for discovering and scoring company career page URLs."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.discovery.link_utils import clean_url, normalize_url

COMMON_CAREER_PATHS = (
    "/careers",
    "/career",
    "/jobs",
    "/job-openings",
    "/open-positions",
    "/openings",
    "/current-openings",
    "/join-us",
    "/join",
    "/work-with-us",
    "/team",
    "/about/careers",
    "/company/careers",
    "/careers/",
    "#/careers",
    "/#careers",
)

CAREER_POSITIVE_TERMS = (
    "careers",
    "jobs",
    "open positions",
    "openings",
    "join our team",
    "work with us",
    "hiring",
    "opportunities",
    "employment",
    "current openings",
    "apply",
    "open roles",
    "join us",
)

CAREER_NEGATIVE_TERMS = (
    "privacy",
    "terms",
    "contact",
    "news",
    "blog",
    "investors",
    "publications",
    "products",
    "services",
)

CAREER_ANCHOR_TERMS = (
    "careers",
    "jobs",
    "join us",
    "join our team",
    "work with us",
    "open roles",
    "opportunities",
    "hiring",
    "current openings",
    "we're hiring",
    "we are hiring",
)

ATS_DOMAIN_FRAGMENTS = (
    "greenhouse.io",
    "boards.greenhouse.io",
    "lever.co",
    "jobs.lever.co",
    "ashbyhq.com",
    "jobs.ashbyhq.com",
    "workable.com",
    "bamboohr.com",
    "smartrecruiters.com",
    "icims.com",
    "workdayjobs.com",
    "myworkdayjobs.com",
    "recruitee.com",
    "teamtailor.com",
    "applytojob.com",
    "comeet.com",
    "personio.com",
    "notion.site",
)

CAREER_PATH_HINTS = ("career", "jobs", "join", "opening", "hiring", "opportunit")

JOB_PORTAL_LINK_TERMS = (
    "current job openings",
    "current openings",
    "see openings",
    "see current openings",
    "view openings",
    "view all jobs",
    "all jobs",
    "search jobs",
    "job openings",
    "open positions",
    "job search",
    "browse jobs",
    "explore careers",
)


def normalize_homepage_url(url: str) -> str | None:
    """Normalize a company homepage URL from inventory."""
    cleaned = clean_url(url)
    if not cleaned:
        return None

    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") + "/"
    return f"{parsed.scheme}://{parsed.netloc}{path if path != '/' else '/'}"


def build_common_career_urls(homepage_url: str) -> list[str]:
    """Build likely career page URLs from a company homepage."""
    parsed = urlparse(homepage_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    candidates: list[str] = []

    for path in COMMON_CAREER_PATHS:
        if path.startswith("#"):
            candidates.append(f"{origin}/{path}")
            candidates.append(f"{origin}{path}")
            continue
        candidates.append(urljoin(origin + "/", path.lstrip("/")))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(candidate)
    return deduped


def is_valid_url(url: str) -> bool:
    """Return True if the string looks like a usable HTTP(S) URL."""
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def get_domain(url: str) -> str:
    """Return the lowercase domain without a leading www."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def is_ats_url(url: str) -> bool:
    """Return True if the URL appears to belong to a known ATS provider."""
    lower_url = url.lower()
    return any(fragment in lower_url for fragment in ATS_DOMAIN_FRAGMENTS)


def extract_links(html: str, base_url: str) -> list[dict[str, str]]:
    """Extract anchor links from HTML with absolute URLs and anchor text."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[dict[str, str]] = []

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue

        absolute = normalize_url(base_url, href)
        if not absolute or not is_valid_url(absolute):
            continue

        text = anchor.get_text(" ", strip=True)
        links.append(
            {
                "href": href,
                "url": absolute,
                "text": text,
            }
        )

    return links


def clean_text(text: str) -> str:
    """Normalize whitespace and lowercase text for term matching."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def contains_career_terms(text: str) -> bool:
    """Return True if text contains career-related keywords."""
    cleaned = clean_text(text)
    return any(term in cleaned for term in CAREER_POSITIVE_TERMS)


def contains_negative_terms(text: str) -> bool:
    """Return True if text contains terms that usually indicate non-career pages."""
    cleaned = clean_text(text)
    return any(term in cleaned for term in CAREER_NEGATIVE_TERMS)


def anchor_looks_like_career_link(text: str, url: str) -> bool:
    """Return True if anchor text or URL looks career-related."""
    combined = clean_text(f"{text} {url}")
    if is_ats_url(url):
        return True
    if any(term in combined for term in CAREER_ANCHOR_TERMS):
        return True
    return any(hint in combined for hint in CAREER_PATH_HINTS)


def url_path_looks_like_career_page(url: str) -> bool:
    """Return True if the URL path suggests a careers/jobs page."""
    path = urlparse(url).path.lower()
    return any(hint in path for hint in CAREER_PATH_HINTS)


def _normalized_path(url: str) -> str:
    path = urlparse(url).path or "/"
    return path.rstrip("/") or "/"


def is_hash_only_career_route(url: str) -> bool:
    """Return True when a URL only adds a careers hash fragment to the homepage path."""
    parsed = urlparse(url)
    path = _normalized_path(url)
    if path != "/":
        return False
    fragment = clean_text(parsed.fragment)
    if not fragment:
        return False
    return any(hint in fragment for hint in CAREER_PATH_HINTS)


def is_effectively_homepage(homepage: str, url: str) -> bool:
    """Return True when url resolves to the company homepage, not a distinct careers page."""
    if not homepage or not url:
        return False
    if get_domain(homepage) != get_domain(url):
        return False
    if is_hash_only_career_route(url):
        return True

    home_path = _normalized_path(homepage)
    url_path = _normalized_path(url)
    if url_path != home_path and url_path != "/":
        return False
    if url_path_looks_like_career_page(url):
        return False
    return True


def is_careers_subdomain(url: str) -> bool:
    """Return True for dedicated careers subdomains such as careers.example.com."""
    domain = get_domain(url)
    return domain.startswith("careers.") or domain.startswith("jobs.")


def looks_like_job_portal_link(text: str, url: str) -> bool:
    """Return True if a link likely leads to an actual job listings portal."""
    if is_ats_url(url) or is_careers_subdomain(url):
        return True
    combined = clean_text(f"{text} {url}")
    if any(term in combined for term in JOB_PORTAL_LINK_TERMS):
        return True
    if url_path_looks_like_career_page(url) and any(
        term in combined for term in ("opening", "posting", "search")
    ):
        return True
    return False


def extract_portal_links(html: str, base_url: str) -> list[dict[str, str]]:
    """Extract links that likely lead from a careers hub to job listings."""
    portal_links: list[dict[str, str]] = []
    for link in extract_links(html, base_url):
        if looks_like_job_portal_link(link["text"], link["url"]):
            portal_links.append(link)
    return portal_links


def score_career_url(
    url: str,
    anchor_text: str = "",
    page_text: str = "",
    final_url: str = "",
    homepage: str = "",
) -> tuple[float, str]:
    """Score a candidate career URL and return (confidence, notes)."""
    if not is_valid_url(url):
        return 0.0, "Invalid URL"

    resolved = final_url or url
    if homepage and is_effectively_homepage(homepage, resolved):
        return 0.0, "Same as company homepage, not a distinct careers page"
    if is_hash_only_career_route(resolved):
        return 0.0, "Hash-only careers route on homepage"

    if is_ats_url(url):
        return 0.95, "External ATS link detected"

    if is_careers_subdomain(resolved):
        return 0.92, "Dedicated careers subdomain"

    combined = clean_text(f"{url} {anchor_text} {page_text} {final_url}")
    has_career_terms = contains_career_terms(combined)
    has_negative_terms = contains_negative_terms(combined)
    path_match = url_path_looks_like_career_page(final_url or url)
    anchor_match = anchor_looks_like_career_link(anchor_text, url)

    if has_negative_terms and not has_career_terms and not path_match:
        return 0.0, "Likely non-career page"

    if path_match and has_career_terms:
        return 0.90, "Career path and page text match"

    if anchor_match and has_career_terms:
        return 0.85, "Homepage career link with supporting page text"

    if anchor_match:
        return 0.80, "Homepage career link"

    if path_match:
        return 0.70, "Common career path match"

    if has_career_terms:
        return 0.50, "Page mentions hiring but URL is weak"

    return 0.0, "No strong career signals"
