"""Persist filtered job candidates to SQLite without duplicates."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from src.database.company_upsert import upsert_company_from_job
from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.jobs.job_models import JobCandidate
from src.jobs.job_url_utils import compute_content_hash, normalize_job_url


@dataclass
class SaveJobsResult:
    inserted: int = 0
    duplicates_skipped: int = 0
    updated: int = 0
    companies_created: int = 0
    skipped_no_company: int = 0


@dataclass
class SaveJobsOptions:
    force_refresh: bool = False
    create_company_if_missing: bool = False
    pending_evaluation: bool = False
    source_board: str | None = None
    discovery_run_id: str | None = None


def resolve_company_id(connection: sqlite3.Connection, candidate: JobCandidate) -> int | None:
    if candidate.company_id is not None:
        row = connection.execute(
            "SELECT company_id FROM companies WHERE company_id = ? LIMIT 1;",
            (candidate.company_id,),
        ).fetchone()
        if row is not None:
            return int(row["company_id"])

    row = connection.execute(
        "SELECT company_id FROM companies WHERE company_name = ? COLLATE NOCASE LIMIT 1;",
        (candidate.company_name,),
    ).fetchone()
    if row is not None:
        return int(row["company_id"])

    return None


def _find_existing_job_id(
    connection: sqlite3.Connection,
    *,
    company_id: int,
    title: str,
    location: str | None,
    url: str | None,
    content_hash: str,
) -> int | None:
    normalized_url = normalize_job_url(url)
    if normalized_url:
        row = connection.execute(
            "SELECT job_id FROM job_postings WHERE url = ? LIMIT 1;",
            (normalized_url,),
        ).fetchone()
        if row is not None:
            return int(row["job_id"])

    row = connection.execute(
        """
        SELECT job_id FROM job_postings
        WHERE company_id = ?
          AND lower(title) = lower(?)
          AND coalesce(lower(location), '') = coalesce(lower(?), '')
        LIMIT 1;
        """,
        (company_id, title, location or ""),
    ).fetchone()
    if row is not None:
        return int(row["job_id"])

    rows = connection.execute(
        "SELECT job_id, title, description, url FROM job_postings WHERE company_id = ?;",
        (company_id,),
    ).fetchall()
    for existing in rows:
        existing_hash = compute_content_hash(
            existing["title"],
            existing["description"],
            existing["url"],
        )
        if existing_hash == content_hash:
            return int(existing["job_id"])
    return None


def _build_fit_reason(candidate: JobCandidate) -> str:
    keywords = ", ".join(candidate.matched_keywords[:8])
    provider = candidate.provider or "unknown"
    parts = [f"provider={provider}"]
    if candidate.triage_score is not None:
        parts.append(f"triage={candidate.triage_score:.1f}")
    if keywords:
        parts.append(f"matched={keywords}")
    else:
        parts.append("matched=none")
    if candidate.llm_fit_score is not None:
        parts.append(f"llm_fit={candidate.llm_fit_score:.1f}")
    return "; ".join(parts)


def _resolve_fit_score(candidate: JobCandidate) -> float | None:
    if candidate.llm_fit_score is not None:
        return round(candidate.llm_fit_score, 2)
    if candidate.keyword_score > 0:
        return round(candidate.keyword_score * 10, 2)
    return None


def _serialize_matched_keywords(keywords: list[str]) -> str | None:
    if not keywords:
        return None
    return json.dumps(keywords)


def save_jobs(
    candidates: list[JobCandidate],
    *,
    force_refresh: bool = False,
    create_company_if_missing: bool = False,
    pending_evaluation: bool = False,
    source_board: str | None = None,
    discovery_run_id: str | None = None,
    options: SaveJobsOptions | None = None,
) -> SaveJobsResult:
    """Insert new jobs into job_postings, skipping duplicates unless force_refresh."""
    if options is not None:
        force_refresh = options.force_refresh
        create_company_if_missing = options.create_company_if_missing
        pending_evaluation = options.pending_evaluation
        source_board = options.source_board
        discovery_run_id = options.discovery_run_id

    result = SaveJobsResult()
    connection = get_connection()

    try:
        apply_migrations(connection)
        for candidate in candidates:
            company_id = resolve_company_id(connection, candidate)
            if company_id is None:
                if create_company_if_missing:
                    company_id = upsert_company_from_job(
                        connection,
                        company_name=candidate.company_name,
                        job_url=candidate.url,
                        location=candidate.location,
                    )
                    result.companies_created += 1
                else:
                    result.skipped_no_company += 1
                    continue

            content_hash = candidate.content_hash or compute_content_hash(
                candidate.title,
                candidate.description,
                candidate.url,
            )
            existing_job_id = _find_existing_job_id(
                connection,
                company_id=company_id,
                title=candidate.title,
                location=candidate.location,
                url=candidate.url,
                content_hash=content_hash,
            )

            fit_score = None if pending_evaluation else _resolve_fit_score(candidate)
            fit_reason = None if pending_evaluation else _build_fit_reason(candidate)
            fit_details = None if pending_evaluation else candidate.fit_details
            board = source_board or candidate.provider
            matched_keywords_json = _serialize_matched_keywords(candidate.matched_keywords)

            if existing_job_id is not None:
                if force_refresh:
                    connection.execute(
                        """
                    UPDATE job_postings
                        SET company_id = ?,
                            title = ?,
                            location = ?,
                            url = ?,
                            description = ?,
                            active = 1,
                            fit_score = ?,
                            fit_reason = ?,
                            fit_details = ?,
                            evaluated_at = CASE WHEN ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE NULL END,
                            source_board = coalesce(?, source_board),
                            discovery_run_id = coalesce(?, discovery_run_id),
                            keyword_score = ?,
                            matched_keywords = ?
                        WHERE job_id = ?;
                        """,
                        (
                            company_id,
                            candidate.title,
                            candidate.location,
                            candidate.url,
                            candidate.description,
                            fit_score,
                            fit_reason,
                            fit_details,
                            fit_details,
                            board,
                            discovery_run_id,
                            candidate.keyword_score,
                            matched_keywords_json,
                            existing_job_id,
                        ),
                    )
                    result.updated += 1
                else:
                    existing = connection.execute(
                        "SELECT description FROM job_postings WHERE job_id = ?;",
                        (existing_job_id,),
                    ).fetchone()
                    existing_description = str(existing["description"] or "").strip() if existing else ""
                    if candidate.description and not existing_description:
                        connection.execute(
                            """
                            UPDATE job_postings
                            SET description = ?,
                                description_status = 'enriched',
                                description_source = 'rediscovery',
                                description_source_url = ?,
                                description_checked_at = CURRENT_TIMESTAMP,
                                description_error = NULL,
                                fit_score = NULL,
                                fit_reason = NULL,
                                fit_details = NULL,
                                evaluated_at = NULL,
                                active = 1
                            WHERE job_id = ?;
                            """,
                            (candidate.description, candidate.url, existing_job_id),
                        )
                        result.updated += 1
                    else:
                        result.duplicates_skipped += 1
                continue

            connection.execute(
                """
                INSERT INTO job_postings (
                    company_id,
                    title,
                    location,
                    url,
                    description,
                    active,
                    fit_score,
                    fit_reason,
                    fit_details,
                    evaluated_at,
                    source_board,
                    discovery_run_id,
                    keyword_score,
                    matched_keywords
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, CASE WHEN ? IS NOT NULL THEN CURRENT_TIMESTAMP END, ?, ?, ?, ?);
                """,
                (
                    company_id,
                    candidate.title,
                    candidate.location,
                    candidate.url,
                    candidate.description,
                    fit_score,
                    fit_reason,
                    fit_details,
                    fit_details,
                    board,
                    discovery_run_id,
                    candidate.keyword_score,
                    matched_keywords_json,
                ),
            )
            result.inserted += 1

        connection.commit()
    finally:
        connection.close()

    return result
