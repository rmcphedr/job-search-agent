"""Validation helpers for agent staging outputs (MVP: use Pydantic models in src.schemas)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.schemas import (
    CompanyCandidate,
    CompanyFitResult,
    JobCandidate,
    JobFitResult,
)

T = TypeVar("T", bound=BaseModel)

_SCHEMA_BY_STEM = {
    "company_candidates": CompanyCandidate,
    "company_evaluations": CompanyFitResult,
    "job_candidates": JobCandidate,
    "job_evaluations": JobFitResult,
}


def infer_schema_from_filename(path: Path) -> type[BaseModel] | None:
    name = path.stem.lower()
    for prefix, model in _SCHEMA_BY_STEM.items():
        if name.startswith(prefix):
            return model
    return None


def infer_schema_from_parent_dir(path: Path) -> type[BaseModel] | None:
    """Infer schema from run folder layout: .../company_candidates/foo.json."""
    parent = path.parent.name.lower()
    return _SCHEMA_BY_STEM.get(parent)


def infer_schema(path: Path) -> type[BaseModel] | None:
    return infer_schema_from_parent_dir(path) or infer_schema_from_filename(path)


def _parse_json_payload(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_staging_records(
    path: Path,
    model: type[T] | None = None,
) -> tuple[list[T], list[str]]:
    """Parse staging JSON as a single object or array; return valid records and errors."""
    model = model or infer_schema(path)
    if model is None:
        raise ValueError(f"Cannot infer schema for {path.name}")

    payload = _parse_json_payload(path)
    rows: list[object]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = [payload]
    else:
        raise ValueError("Staging file must be a JSON object or array")

    records: list[T] = []
    errors: list[str] = []
    for index, row in enumerate(rows):
        try:
            records.append(model.model_validate(row))  # type: ignore[arg-type]
        except ValidationError as exc:
            label = f"row {index}" if isinstance(payload, list) else "record"
            errors.append(f"{label}: {exc}")
    return records, errors


def load_staging_file(path: Path, model: type[T] | None = None) -> tuple[list[T], list[str]]:
    """Backward-compatible alias for :func:`load_staging_records`."""
    return load_staging_records(path, model)
