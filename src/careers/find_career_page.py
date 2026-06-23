"""Find company career pages from homepage URLs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from src.discovery.fetch import get_request_timeout, get_user_agent
from src.careers.career_url_utils import (
    anchor_looks_like_career_link,
    build_common_career_urls,
    extract_links,
    is_valid_url,
    normalize_homepage_url,
    score_career_url,
    url_path_looks_like_career_page,
)

logger = logging.getLogger(__name__)

MIN_FOUND_CONFIDENCE = 0.60
MAX_PAGE_TEXT_CHARS = 50_000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fetch_page(url: str, timeout: int | None = None) -> tuple[int, str, str]:
    """Fetch a URL and return status code, final URL, and truncated page text."""
    request_timeout = timeout if timeout is not None else get_request_timeout()
    headers = {"User-Agent": get_user_agent()}

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=request_timeout,
            allow_redirects=True,
        )
    except requests.Timeout:
        logger.warning("Timeout fetching %s", url)
        return 0, url, ""
    except requests.RequestException as exc:
        logger.warning("Request failed for %s: %s", url, exc)
        return 0, url, ""

    text = response.text[:MAX_PAGE_TEXT_CHARS] if response.text else ""
    return response.status_code, response.url, text


def _is_fetch_success(status_code: int) -> bool:
    return status_code in {200, 301, 302}


def _result_not_found(notes: str = "No career page detected") -> dict[str, Any]:
    return {
        "career_page": "NOT FOUND",
        "status": "NOT FOUND",
        "confidence": 0.0,
        "notes": notes,
        "checked_at": _utc_now_iso(),
    }


def _result_error(message: str) -> dict[str, Any]:
    return {
        "career_page": "NOT FOUND",
        "status": "ERROR",
        "confidence": 0.0,
        "notes": message,
        "checked_at": _utc_now_iso(),
    }


def _result_found(url: str, confidence: float, notes: str) -> dict[str, Any]:
    return {
        "career_page": url,
        "status": "FOUND",
        "confidence": round(confidence, 2),
        "notes": notes,
        "checked_at": _utc_now_iso(),
    }


def _evaluate_candidate(
    url: str,
    *,
    anchor_text: str = "",
    page_text: str = "",
    final_url: str = "",
) -> tuple[float, str]:
    return score_career_url(
        url=url,
        anchor_text=anchor_text,
        page_text=page_text,
        final_url=final_url or url,
    )


def _is_same_as_homepage(homepage: str, url: str) -> bool:
    homepage_clean = normalize_homepage_url(homepage)
    if not homepage_clean:
        return False
    return homepage_clean.rstrip("/") == (url or "").rstrip("/")


def find_career_page(homepage_url: str) -> dict[str, Any]:
    """
    Discover a company's career page URL from its homepage.

    Returns a dict with career_page, status, confidence, notes, and checked_at.
    """
    normalized_homepage = normalize_homepage_url(homepage_url)
    if not normalized_homepage or not is_valid_url(normalized_homepage):
        return _result_error(f"Invalid homepage URL: {homepage_url!r}")

    best_url = ""
    best_confidence = 0.0
    best_notes = ""

    def consider(
        url: str,
        *,
        anchor_text: str = "",
        page_text: str = "",
        final_url: str = "",
    ) -> None:
        nonlocal best_url, best_confidence, best_notes
        confidence, notes = _evaluate_candidate(
            url,
            anchor_text=anchor_text,
            page_text=page_text,
            final_url=final_url,
        )
        if confidence > best_confidence:
            if _is_same_as_homepage(normalized_homepage, final_url or url):
                if not url_path_looks_like_career_page(final_url or url):
                    confidence = min(confidence, 0.50)
            if confidence > best_confidence:
                best_confidence = confidence
                best_url = final_url or url
                best_notes = notes

    for candidate_url in build_common_career_urls(normalized_homepage):
        status_code, final_url, page_text = _fetch_page(candidate_url)
        if not _is_fetch_success(status_code):
            continue
        consider(
            candidate_url,
            page_text=page_text,
            final_url=final_url,
        )
        if best_confidence >= 0.95:
            break

    if best_confidence >= MIN_FOUND_CONFIDENCE:
        return _result_found(best_url, best_confidence, best_notes)

    homepage_status, homepage_final, homepage_html = _fetch_page(normalized_homepage)
    if not _is_fetch_success(homepage_status):
        if best_confidence >= MIN_FOUND_CONFIDENCE:
            return _result_found(best_url, best_confidence, best_notes)
        return _result_error(f"Failed to fetch homepage (status={homepage_status})")

    for link in extract_links(homepage_html, homepage_final):
        if not anchor_looks_like_career_link(link["text"], link["url"]):
            continue

        status_code, final_url, page_text = _fetch_page(link["url"])
        if not _is_fetch_success(status_code):
            consider(
                link["url"],
                anchor_text=link["text"],
                page_text=homepage_html[:5000],
                final_url=link["url"],
            )
            continue

        consider(
            link["url"],
            anchor_text=link["text"],
            page_text=page_text,
            final_url=final_url,
        )

    if best_confidence >= MIN_FOUND_CONFIDENCE:
        return _result_found(best_url, best_confidence, best_notes)

    return _result_not_found(best_notes or "No career page detected")
