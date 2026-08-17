"""Shared job-description enrichment and expiration handling."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.database.db import get_connection
from src.database.import_inventory import get_inventory_path
from src.database.migrate import apply_migrations
from src.jobs.job_detail_parsers import parse_job_detail_from_html
from src.jobs.job_extractors import extract_jobs_from_career_page, fetch_page
from src.orchestration.job_evaluation_queue import cancel_job, sync_job_eligibility
from src.jobs.job_url_utils import is_valid_http_url, normalize_job_url

LINKEDIN_DOMAINS = frozenset({"linkedin.com", "ca.linkedin.com", "www.linkedin.com"})
BROWSER_ENRICHMENT_SOURCES = frozenset({"linkedin", "eluta"})
EXPIRED_MARKERS = (
    "job is no longer available",
    "job posting has expired",
    "position has been filled",
    "position is no longer available",
    "this job has expired",
    "this posting is no longer available",
)


@dataclass(frozen=True)
class DescriptionEnrichmentResult:
    status: str
    description: str | None = None
    source: str | None = None
    source_url: str | None = None
    error: str | None = None
    location: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _is_linkedin(url: str) -> bool:
    domain = _domain(url)
    return domain in LINKEDIN_DOMAINS or domain.endswith(".linkedin.com")


def _repair_known_source_url(job: dict[str, Any], url: str) -> str:
    """Repair malformed URLs produced by older board adapters."""
    if str(job.get("source_board") or "").casefold() == "biospace" and url.startswith("https:///job/"):
        return f"https://jobs.biospace.com{url.removeprefix('https://')}"
    return url


def _normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _title_matches(expected: str, candidate: str) -> bool:
    left = _normalized_title(expected)
    right = _normalized_title(candidate)
    return left == right or SequenceMatcher(None, left, right).ratio() >= 0.88


def _browser_description(html: str, url: str) -> tuple[str | None, str | None]:
    """Extract a job description from a rendered LinkedIn or Eluta detail page."""
    soup = BeautifulSoup(html, "html.parser")
    domain = _domain(url)
    selectors = (
        (
            ".show-more-less-html__markup",
            ".description__text",
            ".jobs-description-content__text",
            ".jobs-box__html-content",
        )
        if domain.endswith("linkedin.com")
        else (
            ".job-description",
            ".jobad-jobdescription",
            "[class*='job-description']",
            "[id*='job-description']",
            "main",
        )
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if len(text) >= 120:
            parsed = parse_job_detail_from_html(html, url)
            return text, str(parsed.get("location") or "").strip() or None
    return None, None


def _enrich_from_browser(url: str, browser: Any) -> DescriptionEnrichmentResult:
    try:
        fetched = browser.get_page_html(url, extra_wait_ms=2500)
    except Exception as exc:
        return DescriptionEnrichmentResult(
            status="error",
            source="browser_rendered_posting",
            source_url=normalize_job_url(url),
            error=f"Browser fetch failed: {exc}",
        )
    source_url = normalize_job_url(fetched.final_url or url)
    if fetched.blocked_reason:
        return DescriptionEnrichmentResult(
            status="error",
            source="browser_rendered_posting",
            source_url=source_url,
            error=f"Browser page was blocked: {fetched.blocked_reason}",
        )
    lowered = fetched.html.lower()
    if any(marker in lowered for marker in EXPIRED_MARKERS):
        return DescriptionEnrichmentResult(
            status="expired",
            source="browser_rendered_posting",
            source_url=source_url,
            error="Rendered posting reports that the role is no longer available",
        )
    description, location = _browser_description(fetched.html, source_url)
    if description:
        return DescriptionEnrichmentResult(
            status="enriched",
            description=description,
            source="browser_rendered_posting",
            source_url=source_url,
            location=location,
        )
    return DescriptionEnrichmentResult(
        status="not_found",
        source="browser_rendered_posting",
        source_url=source_url,
        error="Rendered page did not contain a recognizable job description",
    )


def _career_page_for_company(company_name: str, inventory_path: Path | None = None) -> str | None:
    path = inventory_path or get_inventory_path()
    if not path.is_file():
        return None
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("company_name") or "").strip().casefold() != company_name.strip().casefold():
                continue
            career_page = str(row.get("career_page") or "").strip()
            if career_page and career_page.upper() != "NOT FOUND":
                return career_page
    return None


def enrich_description(
    job: dict[str, Any],
    *,
    inventory_path: Path | None = None,
    browser: Any | None = None,
) -> DescriptionEnrichmentResult:
    """Resolve a description from an authoritative posting or employer career page."""
    url = _repair_known_source_url(job, str(job.get("url") or "").strip())
    company_name = str(job.get("company_name") or "").strip()
    title = str(job.get("title") or "").strip()

    source_board = str(job.get("source_board") or job.get("provider") or "").casefold()
    browser_result: DescriptionEnrichmentResult | None = None
    if browser is not None and (source_board in BROWSER_ENRICHMENT_SOURCES or _is_linkedin(url)):
        browser_result = _enrich_from_browser(url, browser)
        if browser_result.status in {"enriched", "expired"}:
            return browser_result

    direct_fetch_failed = False
    if is_valid_http_url(url) and not _is_linkedin(url):
        status_code, final_url, html = fetch_page(url)
        direct_fetch_failed = status_code == 0
        normalized_url = normalize_job_url(final_url or url)
        if status_code in {404, 410}:
            return DescriptionEnrichmentResult(
                status="expired", source="original_posting", source_url=normalized_url,
                error=f"Posting returned HTTP {status_code}",
            )
        lower_html = html.lower() if html else ""
        if status_code == 200 and any(marker in lower_html for marker in EXPIRED_MARKERS):
            return DescriptionEnrichmentResult(
                status="expired", source="original_posting", source_url=normalized_url,
                error="Posting page reports that the role is no longer available",
            )
        if status_code == 200 and html:
            parsed = parse_job_detail_from_html(html, final_url or url)
            description = str(parsed.get("description_raw") or "").strip()
            if len(description) >= 120:
                return DescriptionEnrichmentResult(
                    status="enriched",
                    description=description,
                    source="original_posting",
                    source_url=normalized_url,
                    location=str(parsed.get("location") or "").strip() or None,
                )

    career_page = _career_page_for_company(company_name, inventory_path)
    if career_page:
        result = extract_jobs_from_career_page(
            career_page,
            company_name=company_name,
            company_id=int(job["company_id"]) if job.get("company_id") is not None else None,
            enrich_details=True,
        )
        candidates = list(result.get("jobs") or [])
        match = next((candidate for candidate in candidates if _title_matches(title, candidate.title)), None)
        if match and match.description and len(match.description.strip()) >= 120:
            return DescriptionEnrichmentResult(
                status="enriched",
                description=match.description.strip(),
                source="employer_career_page",
                source_url=normalize_job_url(match.url or career_page),
                location=match.location,
            )

    if direct_fetch_failed or (browser_result is not None and browser_result.status == "error"):
        return DescriptionEnrichmentResult(
            status="error",
            source=browser_result.source if browser_result else "original_posting",
            source_url=(browser_result.source_url if browser_result else normalize_job_url(url)),
            error=(browser_result.error if browser_result else "Posting could not be fetched; retry later or resolve through the employer site"),
        )

    reason = "LinkedIn lead could not be resolved to an employer posting" if _is_linkedin(url) else "No authoritative description found"
    return DescriptionEnrichmentResult(
        status="not_found",
        source="employer_lookup" if _is_linkedin(url) else "original_posting",
        source_url=career_page or normalize_job_url(url),
        error=reason,
    )


def apply_enrichment_result(job_id: int, result: DescriptionEnrichmentResult) -> None:
    """Persist enrichment metadata and deactivate authoritative expired postings."""
    connection = get_connection()
    try:
        apply_migrations(connection)
        existing = connection.execute(
            "SELECT description FROM job_postings WHERE job_id = ?;", (job_id,)
        ).fetchone()
        old_description = str(existing["description"] or "").strip() if existing else ""
        new_description = str(result.description or "").strip()
        description_changed = bool(
            result.status == "enriched"
            and new_description
            and new_description != old_description
        )
        connection.execute(
            """
            UPDATE job_postings
            SET description = CASE WHEN ? IS NOT NULL THEN ? ELSE description END,
                location = CASE WHEN ? IS NOT NULL AND TRIM(?) != '' THEN ? ELSE location END,
                active = CASE WHEN ? = 'expired' THEN 0 ELSE active END,
                description_status = ?,
                description_source = ?,
                description_source_url = ?,
                description_checked_at = ?,
                description_error = ?
            WHERE job_id = ?;
            """,
            (
                result.description, result.description,
                result.location, result.location, result.location,
                result.status, result.status, result.source, result.source_url,
                _utc_now(), result.error, job_id,
            ),
        )
        if description_changed:
            connection.execute(
                """
                UPDATE job_postings
                SET fit_score = NULL, fit_reason = NULL, fit_details = NULL, evaluated_at = NULL
                WHERE job_id = ?;
                """,
                (job_id,),
            )
            sync_job_eligibility(
                job_id,
                description_ready=True,
                reactivate=True,
                connection=connection,
            )
        elif result.status == "enriched":
            sync_job_eligibility(job_id, description_ready=True, connection=connection)
        if result.status == "expired":
            cancel_job(job_id, "job_expired", connection=connection)
            connection.execute(
                """
                UPDATE tracked_jobs
                SET stage = 'withdrawn', updated_at = ?
                WHERE job_id = ? AND stage IN ('tracked', 'applying');
                """,
                (_utc_now(), job_id),
            )
        connection.commit()
    finally:
        connection.close()


def mark_job_expired(job_id: int, reason: str = "Marked expired by user") -> None:
    apply_enrichment_result(
        job_id,
        DescriptionEnrichmentResult(status="expired", source="user_review", error=reason),
    )


def mark_job_duplicate(job_id: int, canonical_job_id: int) -> None:
    """Keep a duplicate for audit history while removing it from active workflows."""
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.execute(
            """
            UPDATE job_postings
            SET active = 0,
                description_status = 'duplicate',
                description_error = ?,
                description_checked_at = ?,
                fit_score = NULL,
                fit_reason = NULL,
                fit_details = NULL,
                evaluated_at = NULL
            WHERE job_id = ?;
            """,
            (f"Duplicate of job_id={canonical_job_id}", _utc_now(), job_id),
        )
        cancel_job(job_id, "job_duplicate", connection=connection)
        connection.commit()
    finally:
        connection.close()
