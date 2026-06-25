"""Data loaders for the Streamlit dashboard."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

from src.database.db import get_database_path, get_project_root
from src.database.import_inventory import get_inventory_path
from src.discovery.link_utils import clean_url
from src.ui.status_utils import (
    CAREER_STATUS_FOUND,
    CAREER_STATUS_NOT_CHECKED,
    CAREER_STATUS_NOT_FOUND,
    career_page_was_checked,
    extract_company_search_records,
    get_career_page_status,
    get_job_search_status,
    parse_run_notes,
)

logger = logging.getLogger(__name__)

COMPANY_TABLE_COLUMNS = (
    "company_name",
    "industry",
    "location",
    "priority",
    "hiring_status",
    "career_page_status",
    "job_search_status",
    "jobs_found",
    "last_raw_jobs",
    "last_prescreened_jobs",
    "last_triaged_jobs",
    "last_enriched_jobs",
    "last_checked",
    "career_page",
)

JOBS_DISPLAY_COLUMNS = (
    "company_name",
    "title",
    "location",
    "fit_score",
    "fit_reason",
    "date_found",
    "active",
    "url",
)

JOBS_QUERY = """
SELECT
    j.job_id,
    c.company_name,
    c.company_id,
    j.title,
    j.location,
    j.fit_score,
    j.fit_reason,
    j.date_found,
    j.active,
    j.url,
    j.description
FROM job_postings AS j
INNER JOIN companies AS c ON j.company_id = c.company_id
ORDER BY j.fit_score DESC, j.date_found DESC;
"""

ACTIVE_JOBS_COUNT_QUERY = """
SELECT
    c.company_name,
    c.company_id,
    COUNT(*) AS jobs_found
FROM job_postings AS j
INNER JOIN companies AS c ON j.company_id = c.company_id
WHERE j.active = 1
GROUP BY c.company_id, c.company_name;
"""

RUNS_QUERY = """
SELECT
    run_id,
    run_type,
    started_at,
    completed_at,
    companies_checked,
    notes
FROM runs
ORDER BY run_id DESC
LIMIT 50;
"""

COMPANY_PROFILE_QUERY = """
SELECT
    company_summary,
    domain_tags,
    fit_score,
    fit_reason
FROM company_profiles
WHERE company_id = ?
LIMIT 1;
"""


def load_yaml_config(path: Path | str) -> dict[str, Any]:
    """Load a YAML config file and return an empty dict if missing or invalid."""
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = get_project_root() / config_path

    if not config_path.exists():
        logger.warning("Config file not found: %s", config_path)
        return {}

    try:
        with config_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Failed to load config %s: %s", config_path, exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("Config file %s must contain a YAML mapping.", config_path)
        return {}

    return data


@st.cache_data(show_spinner=False)
def load_company_inventory() -> pd.DataFrame:
    """Load raw company inventory from CSV."""
    inventory_path = get_inventory_path()
    columns = [
        "company_id",
        "company_name",
        "website",
        "industry",
        "location",
        "priority",
        "hiring_status",
        "career_page",
        "career_page_status",
        "career_page_checked_at",
        "last_checked",
        "source_id",
        "source_url",
        "source_category",
        "confidence",
        "notes",
    ]
    empty = pd.DataFrame(columns=columns)

    if not inventory_path.exists():
        logger.warning("Company inventory not found: %s", inventory_path)
        return empty

    try:
        frame = pd.read_csv(inventory_path, dtype=str)
    except (OSError, pd.errors.EmptyDataError, ValueError) as exc:
        logger.warning("Failed to read company inventory %s: %s", inventory_path, exc)
        return empty

    if frame.empty:
        logger.warning("Company inventory is empty: %s", inventory_path)
        return empty

    for column in columns:
        if column not in frame.columns:
            frame[column] = ""

    return frame


@st.cache_data(show_spinner=False)
def load_jobs_from_db() -> pd.DataFrame:
    """Load job postings joined with company names from SQLite."""
    empty = pd.DataFrame(columns=[*JOBS_DISPLAY_COLUMNS, "job_id", "company_id", "description"])
    db_path = get_database_path()

    if not db_path.exists():
        logger.warning("Database not found: %s", db_path)
        return empty

    try:
        import sqlite3

        connection = sqlite3.connect(db_path)
        try:
            frame = pd.read_sql_query(JOBS_QUERY, connection)
        finally:
            connection.close()
    except Exception as exc:
        logger.warning("Failed to load jobs from %s: %s", db_path, exc)
        return empty

    if not frame.empty:
        parsed = frame["fit_reason"].map(parse_fit_reason)
        frame["provider"] = parsed.map(lambda item: item.get("provider"))
        frame["matched_keywords"] = parsed.map(lambda item: item.get("matched_keywords"))

    return frame


@st.cache_data(show_spinner=False)
def load_active_job_counts() -> pd.DataFrame:
    """Load active job counts grouped by company."""
    empty = pd.DataFrame(columns=["company_name", "company_id", "jobs_found"])
    db_path = get_database_path()
    if not db_path.exists():
        return empty

    try:
        import sqlite3

        connection = sqlite3.connect(db_path)
        try:
            frame = pd.read_sql_query(ACTIVE_JOBS_COUNT_QUERY, connection)
        finally:
            connection.close()
    except Exception as exc:
        logger.warning("Failed to load job counts from %s: %s", db_path, exc)
        return empty

    return frame


@st.cache_data(show_spinner=False)
def load_run_history() -> pd.DataFrame:
    """Load recent pipeline runs."""
    empty = pd.DataFrame(
        columns=["run_id", "run_type", "started_at", "completed_at", "companies_checked", "notes"]
    )
    db_path = get_database_path()
    if not db_path.exists():
        return empty

    try:
        import sqlite3

        connection = sqlite3.connect(db_path)
        try:
            if not _table_exists(connection, "runs"):
                return empty
            frame = pd.read_sql_query(RUNS_QUERY, connection)
        finally:
            connection.close()
    except Exception as exc:
        logger.warning("Failed to load run history from %s: %s", db_path, exc)
        return empty

    return frame


@st.cache_data(show_spinner=False)
def build_company_dashboard_frame() -> pd.DataFrame:
    """Return company inventory enriched with status labels and job counts."""
    inventory = load_company_inventory()
    if inventory.empty:
        return pd.DataFrame(columns=[*COMPANY_TABLE_COLUMNS, "company_id"])

    job_counts = load_active_job_counts()
    runs = load_run_history()
    search_records = extract_company_search_records(runs)

    counts_by_name: dict[str, int] = {}
    counts_by_id: dict[str, int] = {}
    if not job_counts.empty:
        for _, row in job_counts.iterrows():
            name = str(row.get("company_name", "")).strip()
            company_id = str(row.get("company_id", "")).strip()
            count = int(row.get("jobs_found", 0) or 0)
            if name:
                counts_by_name[name.lower()] = count
            if company_id:
                counts_by_id[company_id] = count

    rows: list[dict[str, object]] = []
    for _, row in inventory.iterrows():
        company_name = str(row.get("company_name", "")).strip()
        company_id = str(row.get("company_id", "")).strip()
        career_page = row.get("career_page")
        career_checked_at = row.get("career_page_checked_at")

        jobs_found = 0
        if company_id and company_id in counts_by_id:
            jobs_found = counts_by_id[company_id]
        elif company_name:
            jobs_found = counts_by_name.get(company_name.lower(), 0)

        search_record = search_records.get(company_name)
        career_checked = career_page_was_checked(career_page, career_checked_at)

        rows.append(
            {
                "company_id": company_id,
                "company_name": company_name,
                "industry": row.get("industry", ""),
                "location": row.get("location", ""),
                "priority": row.get("priority", ""),
                "hiring_status": row.get("hiring_status", ""),
                "career_page_status": get_career_page_status(career_page),
                "job_search_status": get_job_search_status(
                    jobs_found_count=jobs_found,
                    search_record=search_record,
                    career_page_checked=career_checked,
                ),
                "jobs_found": jobs_found,
                "last_raw_jobs": _coerce_int(search_record.get("raw_jobs")) if search_record else 0,
                "last_prescreened_jobs": _coerce_int(search_record.get("prescreened_jobs"))
                if search_record
                else 0,
                "last_triaged_jobs": _coerce_int(search_record.get("triaged_jobs"))
                if search_record
                else 0,
                "last_enriched_jobs": _coerce_int(search_record.get("enriched_jobs"))
                if search_record
                else 0,
                "last_checked": _pick_last_checked(
                    career_checked_at,
                    row.get("last_checked"),
                    search_record.get("checked_at") if search_record else None,
                ),
                "career_page": row.get("career_page", ""),
            }
        )

    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def load_analytics_data() -> dict[str, Any]:
    """Load cached analytics datasets and summary metrics."""
    companies = build_company_dashboard_frame()
    jobs = load_jobs_from_db()
    active_jobs = jobs[jobs["active"].astype(str).isin({"1", "True", "true"})] if not jobs.empty else jobs

    companies_with_career = 0
    companies_missing_career = 0
    if not companies.empty:
        companies_with_career = int((companies["career_page_status"] == CAREER_STATUS_FOUND).sum())
        companies_missing_career = int(
            companies["career_page_status"].isin({CAREER_STATUS_NOT_FOUND, CAREER_STATUS_NOT_CHECKED}).sum()
        )

    companies_with_jobs = 0
    if not companies.empty:
        companies_with_jobs = int((pd.to_numeric(companies["jobs_found"], errors="coerce").fillna(0) > 0).sum())

    total_active_jobs = len(active_jobs)
    avg_jobs = total_active_jobs / len(companies) if len(companies) else 0.0

    top_industries = (
        companies["industry"].fillna("Unknown").replace("", "Unknown").value_counts().head(10).items()
        if not companies.empty
        else []
    )
    top_locations = (
        companies["location"].fillna("Unknown").replace("", "Unknown").value_counts().head(10).items()
        if not companies.empty
        else []
    )

    return {
        "companies": companies,
        "jobs": active_jobs,
        "summary": {
            "total_companies": len(companies),
            "companies_with_career_pages": companies_with_career,
            "companies_missing_career_pages": companies_missing_career,
            "companies_with_jobs": companies_with_jobs,
            "total_active_jobs": total_active_jobs,
            "avg_jobs_per_company": avg_jobs,
            "top_industries": list(top_industries),
            "top_locations": list(top_locations),
        },
    }


def get_company_detail(company_name: str) -> dict[str, Any] | None:
    """Return merged company detail from inventory, dashboard frame, and optional DB profile."""
    inventory = load_company_inventory()
    if inventory.empty:
        return None

    matches = inventory[inventory["company_name"].fillna("").str.lower() == company_name.strip().lower()]
    if matches.empty:
        return None

    row = matches.iloc[0]
    dashboard = build_company_dashboard_frame()
    dash_row = dashboard[dashboard["company_name"].str.lower() == company_name.strip().lower()]
    dash = dash_row.iloc[0].to_dict() if not dash_row.empty else {}

    metadata = parse_company_notes(row.get("notes"))
    profile = _load_company_profile(row.get("company_id"))

    detail = {
        "company_id": row.get("company_id", ""),
        "company_name": row.get("company_name", ""),
        "website": clean_url(str(row.get("website", ""))) or "",
        "industry": row.get("industry", ""),
        "location": row.get("location", ""),
        "priority": row.get("priority", ""),
        "hiring_status": row.get("hiring_status", ""),
        "career_page": clean_url(str(row.get("career_page", ""))) or "",
        "career_page_status": dash.get("career_page_status", get_career_page_status(row.get("career_page"))),
        "job_search_status": dash.get("job_search_status", ""),
        "jobs_found": dash.get("jobs_found", 0),
        "last_checked": dash.get("last_checked", ""),
        "source_id": row.get("source_id", ""),
        "source_url": clean_url(str(row.get("source_url", ""))) or "",
        "source_category": row.get("source_category", ""),
        "confidence": row.get("confidence", ""),
        "notes": row.get("notes", ""),
        "company_summary": profile.get("company_summary") if profile else "",
        "metadata": metadata,
    }
    if profile:
        detail["metadata"]["company_summary"] = profile.get("company_summary") or metadata.get("company_summary")
    return detail


def get_company_jobs(company_name: str) -> pd.DataFrame:
    jobs = load_jobs_from_db()
    if jobs.empty:
        return jobs
    return jobs[jobs["company_name"].fillna("").str.lower() == company_name.strip().lower()].copy()


def get_job_by_id(job_id: int | str) -> dict[str, Any] | None:
    jobs = load_jobs_from_db()
    if jobs.empty:
        return None
    matches = jobs[jobs["job_id"].astype(str) == str(job_id)]
    if matches.empty:
        return None
    return matches.iloc[0].to_dict()


def get_company_run_history(company_name: str) -> list[dict[str, object]]:
    runs = load_run_history()
    if runs.empty:
        return []

    history: list[dict[str, object]] = []
    target = company_name.strip().lower()
    for _, row in runs.iterrows():
        run_type = str(row.get("run_type", ""))
        notes = parse_run_notes(row.get("notes"))
        detail = "—"
        matched = False

        if run_type == "career_discovery":
            companies = notes.get("companies", [])
            if isinstance(companies, list):
                for item in companies:
                    if (
                        isinstance(item, dict)
                        and str(item.get("company_name", "")).strip().lower() == target
                    ):
                        matched = True
                        detail = (
                            f"career_page={item.get('career_page', '—')}, "
                            f"status={item.get('career_page_status', '—')}"
                        )
                        break
        elif run_type == "job_discovery":
            companies = notes.get("companies", {})
            if isinstance(companies, dict):
                for key, payload in companies.items():
                    if str(key).strip().lower() != target or not isinstance(payload, dict):
                        continue
                    matched = True
                    detail = (
                        f"status={payload.get('status', '—')}, "
                        f"filtered={payload.get('filtered_jobs', '—')}, "
                        f"inserted={payload.get('inserted', '—')}, "
                        f"errors={payload.get('message', '—')}"
                    )
                    break

        if matched:
            history.append(
                {
                    "run_type": run_type.replace("_", " ").title(),
                    "time": row.get("started_at", ""),
                    "companies_checked": row.get("companies_checked", ""),
                    "detail": detail,
                }
            )

    return history[:10]


def global_search(query: str) -> dict[str, pd.DataFrame]:
    """Search companies and jobs across key text fields."""
    needle = query.strip().lower()
    empty_companies = pd.DataFrame(columns=COMPANY_TABLE_COLUMNS)
    empty_jobs = pd.DataFrame(columns=[*JOBS_DISPLAY_COLUMNS, "job_id"])

    if not needle:
        return {"companies": empty_companies, "jobs": empty_jobs}

    companies = build_company_dashboard_frame()
    jobs = load_jobs_from_db()

    company_hits = pd.DataFrame(columns=companies.columns)
    if not companies.empty:
        mask = (
            companies["company_name"].fillna("").str.lower().str.contains(needle, regex=False)
            | companies["industry"].fillna("").str.lower().str.contains(needle, regex=False)
        )
        company_hits = companies[mask]

    job_hits = pd.DataFrame(columns=jobs.columns)
    if not jobs.empty:
        search_columns = ["company_name", "title", "description", "fit_reason", "matched_keywords", "location"]
        mask = pd.Series(False, index=jobs.index)
        for column in search_columns:
            if column in jobs.columns:
                mask |= jobs[column].fillna("").astype(str).str.lower().str.contains(needle, regex=False)
        job_hits = jobs[mask]

    return {"companies": company_hits, "jobs": job_hits}


def parse_company_notes(notes: object) -> dict[str, Any]:
    text = _normalize_text(notes)
    if not text:
        return {}
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {"raw_notes": text}
        if isinstance(payload, dict):
            return {
                "description": payload.get("description", ""),
                "specialties": payload.get("specialties", ""),
                "profile_url": payload.get("profile_url", ""),
                "metadata": payload.get("metadata", ""),
                "extraction_method": payload.get("extraction_method", ""),
                "raw_notes": text,
            }
    return {"raw_notes": text}


def parse_fit_reason(fit_reason: object) -> dict[str, str]:
    text = _normalize_text(fit_reason)
    if not text:
        return {"provider": "", "matched_keywords": ""}

    provider = ""
    matched = ""
    provider_match = re.search(r"provider=([^;]+)", text)
    if provider_match:
        provider = provider_match.group(1).strip()
    matched_match = re.search(r"matched=(.+)$", text)
    if matched_match:
        matched = matched_match.group(1).strip()
    return {"provider": provider, "matched_keywords": matched}


def _load_company_profile(company_id: object) -> dict[str, Any] | None:
    company_id_text = _normalize_text(company_id)
    if not company_id_text or not company_id_text.isdigit():
        return None

    db_path = get_database_path()
    if not db_path.exists():
        return None

    try:
        import sqlite3

        connection = sqlite3.connect(db_path)
        try:
            if not _table_exists(connection, "company_profiles"):
                return None
            cursor = connection.execute(COMPANY_PROFILE_QUERY, (int(company_id_text),))
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [description[0] for description in cursor.description]
            return dict(zip(columns, row, strict=False))
        finally:
            connection.close()
    except Exception as exc:
        logger.warning("Failed to load company profile: %s", exc)
        return None


def _pick_last_checked(*values: object) -> str:
    candidates = [_normalize_text(value) for value in values]
    candidates = [value for value in candidates if value]
    if not candidates:
        return ""
    return max(candidates)


def _normalize_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _table_exists(connection, table_name: str) -> bool:
    cursor = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1;",
        (table_name,),
    )
    return cursor.fetchone() is not None
