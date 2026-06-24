"""Prompt builders for company and job fit scoring."""

from __future__ import annotations

import json
from pathlib import Path

from src.database.db import get_project_root

PROMPTS_DIR = get_project_root() / "prompts"
COMPANY_FIT_TEMPLATE_PATH = PROMPTS_DIR / "company_fit.md"
JOB_FIT_TEMPLATE_PATH = PROMPTS_DIR / "job_fit.md"


def _load_template(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def _normalize_field(value: object, *, default: str = "Not provided") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def parse_company_notes(notes: object) -> dict[str, str]:
    """Extract description and specialties from inventory notes JSON."""
    text = _normalize_field(notes, default="")
    if not text:
        return {"description": "", "specialties": ""}
    if not text.startswith("{"):
        return {"description": text, "specialties": ""}

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"description": text, "specialties": ""}

    if not isinstance(payload, dict):
        return {"description": text, "specialties": ""}

    return {
        "description": _normalize_field(payload.get("description"), default=""),
        "specialties": _normalize_field(payload.get("specialties"), default=""),
    }


def build_company_fit_prompt(company_record: dict[str, object]) -> str:
    """Build the company fit scoring prompt from a company record."""
    notes = parse_company_notes(company_record.get("notes", ""))
    template = _load_template(COMPANY_FIT_TEMPLATE_PATH)

    return template.format(
        company_name=_normalize_field(company_record.get("company_name")),
        industry=_normalize_field(company_record.get("industry")),
        website=_normalize_field(company_record.get("website")),
        career_page=_normalize_field(company_record.get("career_page")),
        description=_normalize_field(notes.get("description"), default="Not provided"),
        specialties=_normalize_field(notes.get("specialties"), default="Not provided"),
    )


def build_job_fit_prompt(job_record: dict[str, object], *, company_context: dict[str, str] | None = None) -> str:
    """Build the job fit scoring prompt from a job record."""
    context = company_context or {}
    template = _load_template(JOB_FIT_TEMPLATE_PATH)

    return template.format(
        job_title=_normalize_field(job_record.get("title") or job_record.get("job_title")),
        company_name=_normalize_field(job_record.get("company") or job_record.get("company_name")),
        location=_normalize_field(job_record.get("location")),
        description=_normalize_field(job_record.get("description")),
        industry=_normalize_field(context.get("industry"), default="Not provided"),
        company_description=_normalize_field(context.get("description"), default="Not provided"),
    )
