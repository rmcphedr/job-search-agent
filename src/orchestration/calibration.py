"""Load, save, and apply run calibration feedback."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.orchestration.calibration_models import CalibrationCorrection, CalibrationFile
from src.orchestration.evaluation_store import (
    COMPANY_EVALUATION_COLUMNS,
    company_evaluations_path,
    load_company_evaluations,
)
from src.orchestration.paths import run_dir

logger = logging.getLogger(__name__)

CALIBRATION_FILENAME = "calibration.json"

CALIBRATION_COLUMNS = [
    "original_fit_score",
    "calibrated_fit_score",
    "calibration_feedback",
    "calibrated_at",
]


def calibration_path(run_id: str) -> Path:
    return run_dir(run_id) / CALIBRATION_FILENAME


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def load_calibration(run_id: str) -> CalibrationFile | None:
    path = calibration_path(run_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return CalibrationFile.model_validate(data)


def save_calibration(run_id: str, calibration: CalibrationFile) -> Path:
    path = calibration_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(calibration.model_dump_json(indent=2), encoding="utf-8")
    return path


def append_calibration_entry(
    run_id: str,
    correction: CalibrationCorrection,
    *,
    preference_updates: list[str] | None = None,
) -> CalibrationFile:
    """Merge a correction into the run calibration file."""
    existing = load_calibration(run_id) or CalibrationFile()
    updated_corrections = [
        item for item in existing.corrections if item.company_name.lower() != correction.company_name.lower()
    ]
    updated_corrections.append(correction)
    existing.corrections = updated_corrections
    if preference_updates:
        for item in preference_updates:
            if item not in existing.preference_updates:
                existing.preference_updates.append(item)
    save_calibration(run_id, existing)
    return existing


@dataclass
class CalibrationApplyResult:
    run_id: str
    corrections_applied: int
    companies_updated: list[str]
    skipped: list[str]


def _evaluation_columns() -> list[str]:
    columns = list(COMPANY_EVALUATION_COLUMNS)
    for column in CALIBRATION_COLUMNS:
        if column not in columns:
            columns.append(column)
    return columns


def apply_calibration_to_evaluations(
    run_id: str,
    *,
    evaluations_path: Path | None = None,
) -> CalibrationApplyResult:
    """Apply score corrections from calibration.json to canonical evaluations."""
    calibration = load_calibration(run_id)
    if calibration is None or not calibration.corrections:
        return CalibrationApplyResult(run_id, 0, [], [])

    path = evaluations_path or company_evaluations_path()
    frame = load_company_evaluations(path)
    if frame.empty:
        return CalibrationApplyResult(
            run_id,
            0,
            [],
            [correction.company_name for correction in calibration.corrections],
        )

    for column in CALIBRATION_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    updated_companies: list[str] = []
    skipped: list[str] = []
    applied_count = 0
    now = _utc_now()

    for correction in calibration.corrections:
        mask = frame["company_name"].fillna("").str.strip().str.lower() == correction.company_name.strip().lower()
        if not mask.any():
            skipped.append(correction.company_name)
            continue

        index = frame[mask].index[-1]
        current_score = frame.at[index, "fit_score"]
        if pd.isna(current_score) or frame.at[index, "original_fit_score"] in ("", None) or pd.isna(
            frame.at[index, "original_fit_score"]
        ):
            frame.at[index, "original_fit_score"] = current_score

        frame.at[index, "fit_score"] = correction.corrected_fit_score
        frame.at[index, "calibrated_fit_score"] = correction.corrected_fit_score
        frame.at[index, "calibration_feedback"] = correction.feedback
        frame.at[index, "calibrated_at"] = now
        updated_companies.append(correction.company_name)
        applied_count += 1

    if applied_count:
        output_columns = _evaluation_columns()
        for column in output_columns:
            if column not in frame.columns:
                frame[column] = ""
        frame[output_columns].to_csv(path, index=False)

        calibration.applied_to_evaluations = True
        calibration.applied_at = now
        save_calibration(run_id, calibration)

    return CalibrationApplyResult(run_id, applied_count, updated_companies, skipped)


def get_effective_fit_score(row: pd.Series) -> float | None:
    """Return calibrated score when present, otherwise agent fit_score."""
    calibrated = row.get("calibrated_fit_score")
    if calibrated not in (None, "") and not pd.isna(calibrated):
        try:
            return float(calibrated)
        except (TypeError, ValueError):
            pass
    fit_score = row.get("fit_score")
    if fit_score in (None, "") or pd.isna(fit_score):
        return None
    try:
        return float(fit_score)
    except (TypeError, ValueError):
        return None
