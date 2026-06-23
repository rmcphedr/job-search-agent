"""URL and company-name utilities for directory discovery."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse

IGNORE_TERMS = (
    "privacy",
    "terms",
    "login",
    "sign in",
    "sign-in",
    "subscribe",
    "contact",
    "newsletter",
    "facebook",
    "twitter",
    "x.com",
    "linkedin",
    "instagram",
    "youtube",
    "mailto:",
    "tel:",
)

NAVIGATION_TERMS = (
    "home",
    "about",
    "about us",
    "menu",
    "search",
    "read more",
    "learn more",
    "click here",
    "next",
    "previous",
    "back",
    "skip",
    "make a donation",
    "faire un don",
    "français",
    "english",
    "our companies",
    "startup programs",
    "startups",
    "acceleration program",
    "supply chain",
    "computer vision",
    "3d printing",
    "advanced materials",
    "aerospace",
    "agritech",
)

COMMON_SUFFIXES = (
    "inc",
    "inc.",
    "ltd",
    "ltd.",
    "corp",
    "corp.",
    "co",
    "co.",
    "llc",
    "gmbh",
    "plc",
    "sa",
    "s.a.",
)

URL_TOKEN_PATTERN = re.compile(
    r"(https?://[^\s,;|\"'<>]+|www\.[^\s,;|\"'<>]+)",
    re.IGNORECASE,
)


def clean_url(value: str | None) -> str | None:
    """Normalize a URL for use in code and databases (no trailing space)."""
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if "," in text and text.lower().startswith(("http://", "https://", "www.")):
        text = text.split(",", 1)[0].strip()

    match = URL_TOKEN_PATTERN.search(text)
    if match:
        text = match.group(1).rstrip(".,);]>")
        if text.lower().startswith("www."):
            text = f"http://{text}"

    normalized = normalize_url(text, text) or text
    cleaned = normalized.rstrip("/")
    return cleaned or None


def format_url_for_csv(value: str | None) -> str:
    """Format a URL for CSV storage with a trailing space before the next column."""
    cleaned = clean_url(value)
    if not cleaned:
        return ""
    return f"{cleaned} "


def normalize_url(base_url: str, href: str | None) -> str | None:
    """Resolve a relative href against base_url and return a normalized absolute URL."""
    if not href:
        return None

    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return None

    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None

    normalized = parsed._replace(fragment="")
    return urlunparse(normalized)


def get_domain(url: str | None) -> str | None:
    """Return the lowercase domain for a URL, without a leading www."""
    if not url:
        return None

    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain or None


def is_external_url(url: str, source_domain: str) -> bool:
    """Return True if the URL domain differs from the source domain."""
    domain = get_domain(url)
    if not domain:
        return False

    normalized_source = source_domain.lower().removeprefix("www.")
    return not (domain == normalized_source or domain.endswith(f".{normalized_source}"))


def clean_company_name(text: str | None) -> str | None:
    """Normalize anchor or heading text into a candidate company name."""
    if not text:
        return None

    cleaned = re.sub(r"\s+", " ", text.strip(" \t\n\r-|•·"))
    cleaned = re.sub(r"^\d+[\).\s-]+", "", cleaned)
    cleaned = cleaned.strip(" .,:;|")
    if not cleaned:
        return None

    if len(cleaned) > 120:
        return None

    return cleaned


def should_ignore_link(text: str | None, href: str | None) -> bool:
    """Return True if a link looks like navigation, social, or boilerplate."""
    combined = " ".join(part for part in (text, href) if part).lower()
    if not combined.strip():
        return True

    for term in IGNORE_TERMS:
        if term in combined:
            return True

    if href:
        lower_href = href.lower()
        if lower_href.endswith((".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip")):
            return True
        if "/tag/" in lower_href or "/about-us" in lower_href:
            return True
        if any(
            segment in lower_href
            for segment in (
                "/acceleration-program",
                "/startup-programs",
                "/donation",
                "/privacy",
                "/terms",
                "/login",
            )
        ):
            return True
        if "activitesphilanthropie" in lower_href:
            return True

    cleaned = clean_company_name(text)
    if cleaned and cleaned.lower() in NAVIGATION_TERMS:
        return True

    return False


def looks_like_company_name(text: str | None) -> bool:
    """Heuristic check for whether text resembles a company name."""
    cleaned = clean_company_name(text)
    if not cleaned:
        return False

    if len(cleaned) < 2 or len(cleaned) > 100:
        return False

    lower = cleaned.lower()
    if lower in NAVIGATION_TERMS:
        return False

    if cleaned.isdigit():
        return False

    words = re.findall(r"[A-Za-z0-9&]+", cleaned)
    if not words:
        return False

    if len(words) == 1 and len(words[0]) <= 2:
        return False

    generic_phrases = (
        "member directory",
        "alphabetical listing",
        "view all",
        "see all",
        "our members",
        "company directory",
    )
    if any(phrase in lower for phrase in generic_phrases):
        return False

    return True


def normalize_company_key(company_name: str, website: str | None = None) -> str:
    """Build a stable deduplication key from company name and optional website."""
    name_key = re.sub(r"[^a-z0-9]+", " ", company_name.lower()).strip()
    domain = get_domain(website)
    if domain:
        return f"{name_key}|{domain}"
    return name_key


def text_contains_any(text: str, keywords: list[str]) -> bool:
    """Return True if any keyword appears in text (case-insensitive)."""
    if not text or not keywords:
        return False
    lower_text = text.lower()
    return any(keyword.lower() in lower_text for keyword in keywords)


def score_keyword_match(text: str, include_keywords: list[str], exclude_keywords: list[str]) -> bool:
    """Return True when text matches include keywords and not exclude keywords."""
    if exclude_keywords and text_contains_any(text, exclude_keywords):
        return False
    if include_keywords:
        return text_contains_any(text, include_keywords)
    return True


LSBC_PROFILE_PATH_PATTERN = re.compile(r"^/member/[a-z0-9][a-z0-9-]*/?$", re.IGNORECASE)

LSBC_PROFILE_SLUG_BLOCKLIST = frozenset(
    {
        "login",
        "logout",
        "members",
        "directory",
        "membership",
    }
)


def is_life_sciences_bc_profile_url(url: str | None) -> bool:
    """Return True if the URL looks like a Life Sciences BC member profile page."""
    if not url:
        return False

    parsed = urlparse(url)
    domain = get_domain(url)
    if domain != "lifesciencesbc.ca":
        return False

    path = parsed.path or ""
    if not LSBC_PROFILE_PATH_PATTERN.match(path):
        return False

    slug = path.strip("/").split("/", 1)[1].lower()
    return slug not in LSBC_PROFILE_SLUG_BLOCKLIST


def is_life_sciences_bc_listing_url(url: str | None) -> bool:
    """Return True if the URL is the LSBC alphabetical member listing page."""
    if not url:
        return False

    domain = get_domain(url)
    if domain != "lifesciencesbc.ca":
        return False

    lower_url = url.lower()
    return "alphabetical-listing" in lower_url or lower_url.rstrip("/").endswith(
        "/members-directory"
    )


def has_life_sciences_bc_member_url(*urls: str | None) -> bool:
    """Return True if any URL is a valid Life Sciences BC member profile link."""
    return any(is_life_sciences_bc_profile_url(clean_url(url)) for url in urls if url)
