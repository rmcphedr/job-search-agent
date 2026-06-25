"""HTML extraction strategies for directory source discovery."""

from __future__ import annotations

import json
import logging
from typing import Callable

from bs4 import BeautifulSoup, Tag

from src.discovery.fetch import fetch_url
from src.discovery.link_utils import (
    clean_company_name,
    get_domain,
    is_external_url,
    is_life_sciences_bc_profile_url,
    looks_like_company_name,
    normalize_company_key,
    normalize_url,
    score_keyword_match,
    should_ignore_link,
    text_contains_any,
)
from src.discovery.models import CompanyCandidate, DirectorySource

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

DEFAULT_LSBC_PROFILE_LIMIT = 100
LSBC_DEFAULT_CATEGORY = "Life Sciences BC Member"
LSBC_SOURCE_CATEGORY_MAX_LEN = 80

CARD_SELECTORS = (
    "article",
    'div[class*="card"]',
    'div[class*="startup"]',
    'div[class*="company"]',
    "li",
)


def _get_nearby_text(element: Tag, max_chars: int = 300) -> str:
    texts: list[str] = []
    for chunk in element.stripped_strings:
        texts.append(chunk)
        if sum(len(part) for part in texts) >= max_chars:
            break
    return " ".join(texts)[:max_chars]


def _dedupe_candidates(candidates: list[CompanyCandidate]) -> list[CompanyCandidate]:
    best_by_key: dict[str, CompanyCandidate] = {}
    for candidate in candidates:
        key = normalize_company_key(candidate.company_name, candidate.website)
        existing = best_by_key.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            best_by_key[key] = candidate
    return list(best_by_key.values())


def _make_candidate(
    source: DirectorySource,
    company_name: str,
    website: str | None,
    confidence: float,
    source_category: str | None = None,
    notes: str | None = None,
) -> CompanyCandidate | None:
    cleaned_name = clean_company_name(company_name)
    if not cleaned_name or not looks_like_company_name(cleaned_name):
        return None

    category_terms = {
        term.lower()
        for term in (
            *source.include_categories,
            *source.exclude_categories,
            *source.soft_include_tags,
        )
    }
    if cleaned_name.lower() in category_terms:
        return None

    normalized_website = normalize_url(source.url, website) if website else None
    if not normalized_website:
        return None
    if should_ignore_link(cleaned_name, normalized_website):
        return None

    return CompanyCandidate(
        company_name=cleaned_name,
        website=normalized_website,
        source_id=source.source_id,
        source_name=source.name,
        source_url=source.url,
        source_category=source_category,
        confidence=max(0.0, min(confidence, 1.0)),
        notes=notes or source.notes,
    )


def _confidence_from_keywords(
    text: str,
    source: DirectorySource,
    base: float,
    keyword_boost: float = 0.15,
) -> float:
    confidence = base
    if text_contains_any(text, source.include_keywords):
        confidence += keyword_boost
    if text_contains_any(text, source.include_categories):
        confidence += keyword_boost
    if text_contains_any(text, source.soft_include_tags):
        confidence += keyword_boost / 2
    if text_contains_any(text, source.exclude_keywords):
        confidence -= 0.2
    if text_contains_any(text, source.exclude_categories):
        confidence -= 0.25
    return max(0.0, min(confidence, 1.0))


def _extract_from_links(
    source: DirectorySource,
    html: str,
    *,
    base_confidence: float,
    keyword_boost: float,
    require_keyword_match: bool,
) -> list[CompanyCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[CompanyCandidate] = []

    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue

        href = anchor.get("href")
        text = anchor.get_text(" ", strip=True)
        if should_ignore_link(text, str(href)):
            continue

        parent = anchor.parent if isinstance(anchor.parent, Tag) else anchor
        nearby_text = _get_nearby_text(parent)
        combined_text = f"{text} {nearby_text} {href}"

        if not score_keyword_match(combined_text, source.include_keywords, source.exclude_keywords):
            continue

        company_name = clean_company_name(text)
        if not company_name and href:
            slug = str(href).rstrip("/").split("/")[-1]
            company_name = clean_company_name(slug.replace("-", " ").replace("_", " "))

        if not company_name or not looks_like_company_name(company_name):
            continue

        website = normalize_url(source.url, str(href))
        if not website:
            continue

        if require_keyword_match and source.include_keywords:
            if not (
                text_contains_any(combined_text, source.include_keywords)
                or looks_like_company_name(company_name)
            ):
                continue

        confidence = _confidence_from_keywords(
            combined_text,
            source,
            base=base_confidence,
            keyword_boost=keyword_boost,
        )
        if is_external_url(website, source.source_domain):
            confidence = min(confidence + 0.05, 1.0)

        candidate = _make_candidate(
            source=source,
            company_name=company_name,
            website=website,
            confidence=confidence,
        )
        if candidate is not None:
            candidates.append(candidate)

    return _dedupe_candidates(candidates)


def extract_link_directory(source: DirectorySource, html: str) -> list[CompanyCandidate]:
    """Extract candidates from a page of linked company/profile entries."""
    return _extract_from_links(
        source,
        html,
        base_confidence=0.4,
        keyword_boost=0.15,
        require_keyword_match=False,
    )


def _extract_element_text(element: Tag | None, max_chars: int = 2000) -> str:
    if element is None:
        return ""
    text = element.get_text(" ", strip=True)
    return text[:max_chars]


def _extract_profile_field(
    soup: BeautifulSoup,
    container: Tag | None,
    selector: str,
    *,
    max_chars: int = 2000,
) -> str:
    if container is not None:
        element = container.select_one(selector)
        if element is not None:
            return _extract_element_text(element, max_chars=max_chars)

    element = soup.select_one(selector)
    return _extract_element_text(element, max_chars=max_chars)


def _collect_life_sciences_bc_profile_urls(
    source: DirectorySource,
    html: str,
) -> list[tuple[str, str | None]]:
    """Parse the alphabetical listing and return unique member profile URLs."""
    soup = BeautifulSoup(html, "html.parser")
    seen_urls: set[str] = set()
    profile_links: list[tuple[str, str | None]] = []

    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue

        href = str(anchor.get("href"))
        text = anchor.get_text(" ", strip=True)
        if should_ignore_link(text, href):
            continue

        profile_url = normalize_url(source.url, href)
        if not profile_url or not is_life_sciences_bc_profile_url(profile_url):
            continue

        combined = f"{text} {href}".lower()
        if source.exclude_keywords and text_contains_any(combined, source.exclude_keywords):
            continue

        normalized = profile_url.rstrip("/")
        if normalized in seen_urls:
            continue

        seen_urls.add(normalized)
        profile_links.append((normalized, clean_company_name(text)))

    return profile_links


def _extract_lsbc_website(soup: BeautifulSoup, source_domain: str) -> str | None:
    for company_info in soup.select("div.company-info"):
        for list_item in company_info.select("ul.short-details li"):
            strong = list_item.find("strong")
            label = strong.get_text(" ", strip=True).lower() if strong else ""
            if "website" not in label:
                continue

            anchor = list_item.find("a", href=True)
            if anchor is not None:
                website = normalize_url(f"https://{source_domain}/", str(anchor.get("href")))
                if website and is_external_url(website, source_domain):
                    return website

            link_text = list_item.get_text(" ", strip=True)
            for token in link_text.split():
                if "." in token and not token.startswith("@"):
                    candidate = token.strip(",.;")
                    if candidate.startswith("www."):
                        candidate = f"http://{candidate}"
                    website = normalize_url(f"https://{source_domain}/", candidate)
                    if website and is_external_url(website, source_domain):
                        return website

    return None


def _extract_lsbc_company_name(
    soup: BeautifulSoup,
    container: Tag | None,
    listing_name: str | None,
) -> tuple[str | None, str]:
    if container is not None:
        heading = container.find("h3")
        if heading is not None:
            name = clean_company_name(heading.get_text(" ", strip=True))
            if name:
                return name, "h3"

        mobile_heading = soup.select_one("h2.show-in-mobile")
        if mobile_heading is not None:
            name = clean_company_name(mobile_heading.get_text(" ", strip=True))
            if name:
                return name, "h2.show-in-mobile"

    if listing_name and looks_like_company_name(listing_name):
        return listing_name, "listing_anchor"

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for suffix in ("| Life Sciences BC", "- Life Sciences BC", "| LSBC"):
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    name = clean_company_name(title)
    if name:
        return name, "page_title"

    return None, "missing"


def _build_lsbc_notes(
    profile_url: str,
    description: str,
    specialties: str,
    metadata: str,
) -> str:
    payload = {
        "profile_url": profile_url,
        "description": description,
        "specialties": specialties,
        "metadata": metadata,
        "extraction_method": "life_sciences_bc_profile",
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _choose_lsbc_source_category(specialties: str) -> str:
    cleaned = specialties.strip()
    if cleaned and len(cleaned) <= LSBC_SOURCE_CATEGORY_MAX_LEN:
        return cleaned
    return LSBC_DEFAULT_CATEGORY


def extract_life_sciences_bc_profile(
    source: DirectorySource,
    profile_url: str,
    listing_name: str | None = None,
) -> CompanyCandidate | None:
    """Fetch a Life Sciences BC member profile page and extract a company candidate."""
    status_code, html = fetch_url(profile_url)
    if status_code != 200 or not html.strip():
        logger.warning(
            "Failed to fetch Life Sciences BC profile %s (status=%s)",
            profile_url,
            status_code,
        )
        return None

    try:
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one("div.featured-sponsor.single-author-details")

        company_name, name_source = _extract_lsbc_company_name(soup, container, listing_name)
        if not company_name:
            logger.warning("Missing company name for Life Sciences BC profile %s", profile_url)
            return None

        description = _extract_profile_field(soup, container, "div.description")
        specialties = _extract_profile_field(soup, container, "div.specialties")
        metadata_parts = []
        if container is not None:
            for selector in ("div.membercommas", "div.memberhalf"):
                block = container.select_one(selector)
                block_text = _extract_element_text(block, max_chars=500)
                if block_text:
                    metadata_parts.append(block_text)
        metadata = " | ".join(metadata_parts)

        external_website = _extract_lsbc_website(soup, source.source_domain)
        website = external_website or profile_url

        if external_website and name_source in {"h3", "h2.show-in-mobile", "listing_anchor"}:
            confidence = 0.85
        elif external_website:
            confidence = 0.75
        elif name_source in {"h3", "listing_anchor"}:
            confidence = 0.65
        elif name_source == "h2.show-in-mobile":
            confidence = 0.6
        else:
            confidence = 0.55

        notes = _build_lsbc_notes(profile_url, description, specialties, metadata)

        return CompanyCandidate(
            company_name=company_name,
            website=website,
            source_id=source.source_id,
            source_name=source.name,
            source_url=profile_url,
            source_category=_choose_lsbc_source_category(specialties),
            confidence=confidence,
            notes=notes,
        )
    except Exception as exc:
        logger.warning(
            "Failed to parse Life Sciences BC profile %s: %s",
            profile_url,
            exc,
        )
        return None


def collect_life_sciences_bc_profile_urls(
    source: DirectorySource,
    html: str,
    max_links: int | None = None,
) -> list[tuple[str, str | None]]:
    """Public helper for listing Life Sciences BC profile URLs during debugging."""
    links = _collect_life_sciences_bc_profile_urls(source, html)
    if max_links is not None:
        return links[:max_links]
    return links


def _filter_life_sciences_bc_profile_links(
    profile_links: list[tuple[str, str | None]],
    *,
    profile_offset: int = 0,
    skip_profile_urls: set[str] | None = None,
    profile_limit: int | None = None,
) -> list[tuple[str, str | None]]:
    """Apply offset, skip-existing, and limit to LSBC profile links."""
    filtered = profile_links
    if profile_offset > 0:
        filtered = filtered[profile_offset:]
    if skip_profile_urls:
        filtered = [
            (profile_url, listing_name)
            for profile_url, listing_name in filtered
            if profile_url.rstrip("/") not in skip_profile_urls
        ]
    if profile_limit is not None:
        filtered = filtered[:profile_limit]
    return filtered


def extract_life_sciences_bc_member_directory(
    source: DirectorySource,
    html: str,
    profile_limit: int | None = None,
    profile_offset: int = 0,
    skip_profile_urls: set[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[CompanyCandidate]:
    """Two-step Life Sciences BC extraction: listing page, then member profile pages."""
    profile_links = _collect_life_sciences_bc_profile_urls(source, html)
    total_found = len(profile_links)
    if not profile_links:
        logger.warning("No Life Sciences BC profile links found on listing page.")
        return []

    skipped_existing = 0
    if skip_profile_urls:
        skipped_existing = sum(
            1 for profile_url, _ in profile_links if profile_url.rstrip("/") in skip_profile_urls
        )

    limit = profile_limit if profile_limit is not None else DEFAULT_LSBC_PROFILE_LIMIT
    profile_links = _filter_life_sciences_bc_profile_links(
        profile_links,
        profile_offset=profile_offset,
        skip_profile_urls=skip_profile_urls,
        profile_limit=limit,
    )

    if skip_profile_urls and skipped_existing:
        logger.info(
            "Skipping %s Life Sciences BC profile(s) already in inventory.",
            skipped_existing,
        )
    if profile_offset:
        logger.info("Starting at profile offset %s.", profile_offset)

    if not profile_links:
        logger.warning(
            "No Life Sciences BC profile links left to process (found=%s, offset=%s, skipped=%s).",
            total_found,
            profile_offset,
            skipped_existing,
        )
        return []

    logger.info(
        "Following %s of %s Life Sciences BC profile link(s) (limit=%s).",
        len(profile_links),
        total_found,
        limit,
    )

    candidates: list[CompanyCandidate] = []
    total = len(profile_links)
    for index, (profile_url, listing_name) in enumerate(profile_links, start=1):
        label = listing_name or profile_url
        if progress_callback is not None:
            progress_callback(index, total, f"Fetching profile: {label}")
        candidate = extract_life_sciences_bc_profile(source, profile_url, listing_name)
        if candidate is not None:
            candidates.append(candidate)
            if progress_callback is not None:
                progress_callback(index, total, f"Found company: {candidate.company_name}")

    return _dedupe_candidates(candidates)


def extract_member_directory(
    source: DirectorySource,
    html: str,
    profile_limit: int | None = None,
    profile_offset: int = 0,
    skip_profile_urls: set[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[CompanyCandidate]:
    """Extract candidates from a member directory page."""
    if source.source_id == "life_sciences_bc":
        return extract_life_sciences_bc_member_directory(
            source,
            html,
            profile_limit,
            profile_offset=profile_offset,
            skip_profile_urls=skip_profile_urls,
            progress_callback=progress_callback,
        )

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[CompanyCandidate] = []

    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue

        href = anchor.get("href")
        text = anchor.get_text(" ", strip=True)
        if should_ignore_link(text, str(href)):
            continue

        parent = anchor.parent if isinstance(anchor.parent, Tag) else anchor
        nearby_text = _get_nearby_text(parent)
        combined_text = f"{text} {nearby_text} {href}"

        if source.exclude_keywords and text_contains_any(combined_text, source.exclude_keywords):
            continue

        company_name = clean_company_name(text)
        if not company_name or not looks_like_company_name(company_name):
            continue

        website = normalize_url(source.url, str(href))
        if not website:
            continue

        confidence = 0.6
        if is_external_url(website, source.source_domain):
            confidence += 0.05
        if text_contains_any(combined_text, source.include_keywords):
            confidence += 0.05

        candidate = _make_candidate(
            source=source,
            company_name=company_name,
            website=website,
            confidence=confidence,
        )
        if candidate is not None:
            candidates.append(candidate)

    return _dedupe_candidates(candidates)


def _find_category_in_text(text: str, categories: list[str]) -> str | None:
    for category in categories:
        if category.lower() in text.lower():
            return category
    return None


def extract_card_directory(source: DirectorySource, html: str) -> list[CompanyCandidate]:
    """Extract candidates from card-like startup/company blocks."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[CompanyCandidate] = []
    seen_blocks: set[int] = set()

    for selector in CARD_SELECTORS:
        for block in soup.select(selector):
            if not isinstance(block, Tag):
                continue

            block_id = id(block)
            if block_id in seen_blocks:
                continue
            seen_blocks.add(block_id)

            block_text = _get_nearby_text(block, max_chars=500)
            matched_exclude = _find_category_in_text(block_text, source.exclude_categories)
            if matched_exclude:
                continue

            company_name = None
            for heading in block.find_all(["h1", "h2", "h3", "h4", "h5", "strong"]):
                candidate_name = clean_company_name(heading.get_text(" ", strip=True))
                if candidate_name and looks_like_company_name(candidate_name):
                    company_name = candidate_name
                    break

            website = None
            for anchor in block.find_all("a", href=True):
                href = str(anchor.get("href"))
                if should_ignore_link(anchor.get_text(" ", strip=True), href):
                    continue
                resolved = normalize_url(source.url, href)
                if not resolved:
                    continue
                lower_href = resolved.lower()
                if "/startup" in lower_href or "/company" in lower_href or "/companies" in lower_href:
                    website = resolved
                    if not company_name:
                        company_name = clean_company_name(anchor.get_text(" ", strip=True))
                    break

            if website is None:
                for anchor in block.find_all("a", href=True):
                    href = str(anchor.get("href"))
                    if should_ignore_link(anchor.get_text(" ", strip=True), href):
                        continue
                    resolved = normalize_url(source.url, href)
                    if resolved and is_external_url(resolved, source.source_domain):
                        website = resolved
                        if not company_name:
                            company_name = clean_company_name(anchor.get_text(" ", strip=True))
                        break

            if not company_name:
                continue

            source_category = _find_category_in_text(block_text, source.include_categories)
            confidence = 0.55
            if source_category:
                confidence += 0.15
            if text_contains_any(block_text, source.soft_include_tags):
                confidence += 0.1
            if is_external_url(website or "", source.source_domain):
                confidence += 0.05

            candidate = _make_candidate(
                source=source,
                company_name=company_name,
                website=website,
                confidence=confidence,
                source_category=source_category,
            )
            if candidate is not None:
                candidates.append(candidate)

    if not candidates:
        return extract_link_directory(source, html)

    return _dedupe_candidates(candidates)


def extract_large_directory(source: DirectorySource, html: str) -> list[CompanyCandidate]:
    """Extract candidates from a large directory page."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[CompanyCandidate] = []

    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue

        href = anchor.get("href")
        text = anchor.get_text(" ", strip=True)
        if should_ignore_link(text, str(href)):
            continue

        parent = anchor.parent if isinstance(anchor.parent, Tag) else anchor
        nearby_text = _get_nearby_text(parent)
        combined_text = f"{text} {nearby_text} {href}"

        company_name = clean_company_name(text)
        if not company_name:
            slug = str(href).rstrip("/").split("/")[-1]
            if slug and slug not in {"companies", "company"}:
                company_name = clean_company_name(slug.replace("-", " ").replace("_", " "))

        if not company_name or not looks_like_company_name(company_name):
            continue

        website = normalize_url(source.url, str(href))
        if not website:
            continue

        source_category = _find_category_in_text(combined_text, source.include_categories)
        if source.exclude_categories and _find_category_in_text(combined_text, source.exclude_categories):
            continue

        confidence = 0.5
        if source_category:
            confidence += 0.1
        if text_contains_any(combined_text, source.include_categories):
            confidence += 0.05
        if is_external_url(website, source.source_domain):
            confidence += 0.05

        candidate = _make_candidate(
            source=source,
            company_name=company_name,
            website=website,
            confidence=confidence,
            source_category=source_category,
        )
        if candidate is not None:
            candidates.append(candidate)

    return _dedupe_candidates(candidates)


def extract_link_following(source: DirectorySource, html: str) -> list[CompanyCandidate]:
    """Collect useful links from a landing page without recursive following."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[CompanyCandidate] = []

    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue

        href = anchor.get("href")
        text = anchor.get_text(" ", strip=True)
        if should_ignore_link(text, str(href)):
            continue

        parent = anchor.parent if isinstance(anchor.parent, Tag) else anchor
        nearby_text = _get_nearby_text(parent)
        combined_text = f"{text} {nearby_text} {href}"

        if source.include_keywords and not text_contains_any(combined_text, source.include_keywords):
            continue
        if source.exclude_keywords and text_contains_any(combined_text, source.exclude_keywords):
            continue

        company_name = clean_company_name(text)
        if not company_name or not looks_like_company_name(company_name):
            continue

        website = normalize_url(source.url, str(href))
        if not website:
            continue

        confidence = 0.3
        if text_contains_any(combined_text, source.include_keywords):
            confidence += 0.1
        if is_external_url(website, source.source_domain):
            confidence += 0.1

        candidate = _make_candidate(
            source=source,
            company_name=company_name,
            website=website,
            confidence=confidence,
        )
        if candidate is not None:
            candidates.append(candidate)

    return _dedupe_candidates(candidates)


STRATEGY_HANDLERS: dict[str, Callable[[DirectorySource, str], list[CompanyCandidate]]] = {
    "link_directory": extract_link_directory,
    "member_directory": extract_member_directory,
    "card_directory": extract_card_directory,
    "large_directory": extract_large_directory,
    "link_following": extract_link_following,
}


def extract_candidates(
    source: DirectorySource,
    profile_limit: int | None = None,
    profile_offset: int = 0,
    skip_profile_urls: set[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[CompanyCandidate]:
    """Fetch a directory source page and extract company candidates."""
    status_code, html = fetch_url(source.url)
    if status_code != 200 or not html.strip():
        logger.warning(
            "Skipping source %s (%s): fetch returned status=%s",
            source.source_id,
            source.url,
            status_code,
        )
        return []

    handler = STRATEGY_HANDLERS.get(source.strategy)
    if handler is None:
        logger.warning(
            "Skipping source %s: unknown strategy %r",
            source.source_id,
            source.strategy,
        )
        return []

    try:
        if source.strategy == "member_directory":
            candidates = extract_member_directory(
                source,
                html,
                profile_limit=profile_limit,
                profile_offset=profile_offset,
                skip_profile_urls=skip_profile_urls,
                progress_callback=progress_callback,
            )
        else:
            candidates = handler(source, html)
            if progress_callback is not None and candidates:
                progress_callback(len(candidates), len(candidates), f"Extracted from {source.source_id}")
    except Exception as exc:
        logger.warning(
            "Skipping source %s due to extraction error: %s",
            source.source_id,
            exc,
        )
        return []

    logger.info(
        "Extracted %s candidates from %s using strategy=%s",
        len(candidates),
        source.source_id,
        source.strategy,
    )
    return candidates
