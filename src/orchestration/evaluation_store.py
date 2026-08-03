"""Canonical company evaluation CSV read/write."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.database.db import get_project_root, load_settings
from src.llm.schemas import CompanyFitResult
from src.llm.score_exports import company_result_to_row, upsert_company_fit_rows

logger = logging.getLogger(__name__)

COMPANY_EVALUATION_COLUMNS = [
    "company_name",
    "fit_score",
    "industry_alignment",
    "mission_alignment",
    "career_alignment",
    "growth_potential",
    "reasoning",
    "best_roles",
    "interesting_factors",
    "red_flags",
    "confidence",
    "run_id",
    "source_path",
    "timestamp",
    "original_fit_score",
    "calibrated_fit_score",
    "calibration_feedback",
    "calibrated_at",
]


def company_evaluations_path() -> Path:
    try:
        settings = load_settings()
        paths = settings.get("paths", {})
        if isinstance(paths, dict):
            evaluations = paths.get("company_evaluations")
            if isinstance(evaluations, str) and evaluations.strip():
                return get_project_root() / evaluations
    except RuntimeError:
        pass
    return get_project_root() / "data" / "company_evaluations.csv"


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _join_list(values: list[str]) -> str:
    return "; ".join(value.strip() for value in values if value and value.strip())


def company_evaluation_to_row(
    result: CompanyFitResult,
    *,
    run_id: str | None = None,
    source_path: str | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    return {
        "company_name": result.company_name,
        "fit_score": result.fit_score,
        "industry_alignment": result.industry_alignment,
        "mission_alignment": result.mission_alignment,
        "career_alignment": result.career_alignment,
        "growth_potential": result.growth_potential,
        "reasoning": result.reasoning,
        "best_roles": _join_list(result.best_roles),
        "interesting_factors": _join_list(result.interesting_factors),
        "red_flags": _join_list(result.red_flags),
        "confidence": result.confidence,
        "run_id": run_id or "",
        "source_path": source_path or "",
        "timestamp": timestamp or _utc_timestamp(),
    }


def _read_evaluations(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COMPANY_EVALUATION_COLUMNS)

    try:
        frame = pd.read_csv(path, dtype=str)
    except (OSError, pd.errors.EmptyDataError, ValueError) as exc:
        logger.warning("Failed to read evaluations from %s: %s", path, exc)
        return pd.DataFrame(columns=COMPANY_EVALUATION_COLUMNS)

    for column in COMPANY_EVALUATION_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    numeric_columns = [
        "fit_score",
        "industry_alignment",
        "mission_alignment",
        "career_alignment",
        "growth_potential",
        "confidence",
        "original_fit_score",
        "calibrated_fit_score",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return frame[COMPANY_EVALUATION_COLUMNS]


def has_company_evaluation(company_name: str, path: Path | None = None) -> bool:
    """Return True if canonical evaluations already include this company."""
    evaluations_path = path or company_evaluations_path()
    frame = _read_evaluations(evaluations_path)
    if frame.empty:
        return False
    normalized = company_name.strip().lower()
    names = frame["company_name"].fillna("").str.strip().str.lower()
    return normalized in set(names)


def upsert_company_evaluation(
    result: CompanyFitResult,
    *,
    run_id: str | None = None,
    source_path: str | None = None,
    evaluations_path: Path | None = None,
) -> Path:
    """Merge one evaluation into canonical CSV and legacy outputs export."""
    path = evaluations_path or company_evaluations_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    row = company_evaluation_to_row(result, run_id=run_id, source_path=source_path)
    existing = _read_evaluations(path)
    incoming = pd.DataFrame([row], columns=COMPANY_EVALUATION_COLUMNS)

    if existing.empty:
        merged = incoming
    else:
        combined = pd.concat([existing, incoming], ignore_index=True)
        merged = combined.drop_duplicates(subset=["company_name"], keep="last")
        merged = merged.sort_values("company_name")

    merged.to_csv(path, index=False)

    # Keep legacy outputs/ export in sync for dashboard helpers.
    upsert_company_fit_rows([company_result_to_row(result)])

    return path


def load_company_evaluations(evaluations_path: Path | None = None) -> pd.DataFrame:
    return _read_evaluations(evaluations_path or company_evaluations_path())
