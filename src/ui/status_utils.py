"""Status helpers for company career page and job search state."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

CAREER_STATUS_FOUND = "✅ FOUND"
CAREER_STATUS_NOT_FOUND = "❌ NOT FOUND"
CAREER_STATUS_NOT_CHECKED = "⚠️ NOT CHECKED"

JOB_STATUS_JOBS_FOUND = "✅ JOBS FOUND"
JOB_STATUS_NO_JOBS = "⚠️ NO JOBS FOUND"
JOB_STATUS_ERROR = "❌ ERROR"
JOB_STATUS_NOT_CHECKED = "⚪ NOT CHECKED"

CAREER_FILTER_LABELS = {
    CAREER_STATUS_FOUND: "Found",
    CAREER_STATUS_NOT_FOUND: "Not Found",
    CAREER_STATUS_NOT_CHECKED: "Not Checked",
}

JOB_FILTER_LABELS = {
    JOB_STATUS_JOBS_FOUND: "Jobs Found",
    JOB_STATUS_NO_JOBS: "No Jobs Found",
    JOB_STATUS_ERROR: "Error",
    JOB_STATUS_NOT_CHECKED: "Not Checked",
}


def _normalize_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def get_career_page_status(career_page: object) -> str:
    """Return career page status label with icon."""
    text = _normalize_text(career_page)
    if not text:
        return CAREER_STATUS_NOT_CHECKED
    if text.upper() == "NOT FOUND":
        return CAREER_STATUS_NOT_FOUND
    return CAREER_STATUS_FOUND


def career_page_was_checked(career_page: object, career_page_checked_at: object = None) -> bool:
    """Return True when a career page lookup has been recorded."""
    if _normalize_text(career_page_checked_at):
        return True
    text = _normalize_text(career_page)
    return bool(text)


def get_job_search_status(
    *,
    jobs_found_count: int,
    search_record: dict[str, Any] | None = None,
    career_page_checked: bool = False,
) -> str:
    """Return job search status label with icon."""
    if jobs_found_count > 0:
        return JOB_STATUS_JOBS_FOUND

    if search_record:
        status = str(search_record.get("status", "")).lower()
        if status == "error":
            return JOB_STATUS_ERROR
        if status in {"ok", "no_jobs", "completed"}:
            return JOB_STATUS_NO_JOBS

    if career_page_checked and search_record is None:
        return JOB_STATUS_NOT_CHECKED

    return JOB_STATUS_NOT_CHECKED


def parse_run_notes(notes: object) -> dict[str, Any]:
    """Parse JSON run notes, returning an empty dict when unavailable."""
    text = _normalize_text(notes)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def extract_company_search_records(runs_frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Build a map of company_name -> latest job search record from run history."""
    if runs_frame.empty:
        return {}

    records: dict[str, dict[str, Any]] = {}
    for _, row in runs_frame.iterrows():
        if str(row.get("run_type", "")).lower() != "job_discovery":
            continue
        notes = parse_run_notes(row.get("notes"))
        companies = notes.get("companies", {})
        if not isinstance(companies, dict):
            continue
        for company_name, payload in companies.items():
            name = _normalize_text(company_name)
            if not name or name in records:
                continue
            if isinstance(payload, dict):
                records[name] = payload
    return records
