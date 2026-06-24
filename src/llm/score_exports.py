"""CSV export and dashboard loaders for LLM fit scores."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.database.db import get_project_root, load_settings
from src.llm.schemas import CompanyFitResult, JobFitResult

logger = logging.getLogger(__name__)

COMPANY_FIT_COLUMNS = [
    "company_name",
    "fit_score",
    "reasoning",
    "confidence",
    "timestamp",
]

JOB_FIT_COLUMNS = [
    "job_title",
    "company_name",
    "fit_score",
    "skills_match",
    "skill_gaps",
    "confidence",
    "timestamp",
]


def get_outputs_dir() -> Path:
    try:
        settings = load_settings()
        paths = settings.get("paths", {})
        if isinstance(paths, dict):
            outputs_path = paths.get("outputs")
            if isinstance(outputs_path, str) and outputs_path.strip():
                return get_project_root() / outputs_path
    except RuntimeError:
        pass
    return get_project_root() / "outputs"


def company_fit_export_path() -> Path:
    return get_outputs_dir() / "company_fit_scores.csv"


def job_fit_export_path() -> Path:
    return get_outputs_dir() / "job_fit_scores.csv"


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _join_list(values: list[str]) -> str:
    return "; ".join(value.strip() for value in values if value and value.strip())


def company_result_to_row(result: CompanyFitResult, *, timestamp: str | None = None) -> dict[str, object]:
    return {
        "company_name": result.company_name,
        "fit_score": result.fit_score,
        "reasoning": result.reasoning,
        "confidence": result.confidence,
        "timestamp": timestamp or _utc_timestamp(),
    }


def job_result_to_row(result: JobFitResult, *, timestamp: str | None = None) -> dict[str, object]:
    return {
        "job_title": result.job_title,
        "company_name": result.company_name,
        "fit_score": result.fit_score,
        "skills_match": _join_list(result.skills_match),
        "skill_gaps": _join_list(result.skill_gaps),
        "confidence": result.confidence,
        "timestamp": timestamp or _utc_timestamp(),
    }


def upsert_company_fit_rows(rows: list[dict[str, object]], export_path: Path | None = None) -> Path:
    """Merge company fit rows into the export CSV by company_name."""
    path = export_path or company_fit_export_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_export(path, COMPANY_FIT_COLUMNS)
    incoming = pd.DataFrame(rows, columns=COMPANY_FIT_COLUMNS)
    if incoming.empty:
        return path

    if existing.empty:
        merged = incoming
    else:
        combined = pd.concat([existing, incoming], ignore_index=True)
        combined = combined.drop_duplicates(subset=["company_name"], keep="last")
        merged = combined.sort_values("company_name")

    merged.to_csv(path, index=False)
    return path


def upsert_job_fit_rows(rows: list[dict[str, object]], export_path: Path | None = None) -> Path:
    """Merge job fit rows into the export CSV by job_title + company_name."""
    path = export_path or job_fit_export_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_export(path, JOB_FIT_COLUMNS)
    incoming = pd.DataFrame(rows, columns=JOB_FIT_COLUMNS)
    if incoming.empty:
        return path

    if existing.empty:
        merged = incoming
    else:
        combined = pd.concat([existing, incoming], ignore_index=True)
        combined = combined.drop_duplicates(subset=["job_title", "company_name"], keep="last")
        merged = combined.sort_values(["company_name", "job_title"])

    merged.to_csv(path, index=False)
    return path


def load_company_fit_scores(export_path: Path | None = None) -> pd.DataFrame:
    """Load company fit scores for dashboard use."""
    path = export_path or company_fit_export_path()
    return _read_export(path, COMPANY_FIT_COLUMNS)


def load_job_fit_scores(export_path: Path | None = None) -> pd.DataFrame:
    """Load job fit scores for dashboard use."""
    path = export_path or job_fit_export_path()
    return _read_export(path, JOB_FIT_COLUMNS)


def _read_export(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)

    try:
        frame = pd.read_csv(path, dtype=str)
    except (OSError, pd.errors.EmptyDataError, ValueError) as exc:
        logger.warning("Failed to read fit scores from %s: %s", path, exc)
        return pd.DataFrame(columns=columns)

    for column in columns:
        if column not in frame.columns:
            frame[column] = ""

    if "fit_score" in frame.columns:
        frame["fit_score"] = pd.to_numeric(frame["fit_score"], errors="coerce")
    if "confidence" in frame.columns:
        frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce")

    return frame[columns]
