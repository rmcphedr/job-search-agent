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


def load_staging_file(path: Path, model: type[T] | None = None) -> tuple[list[T], list[str]]:
    """Parse a staging JSON array; return valid records and error strings."""
    model = model or infer_schema_from_filename(path)
    if model is None:
        raise ValueError(f"Cannot infer schema for {path.name}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Staging file must be a JSON array")

    records: list[T] = []
    errors: list[str] = []
    for index, row in enumerate(payload):
        try:
            records.append(model.model_validate(row))  # type: ignore[arg-type]
        except ValidationError as exc:
            errors.append(f"row {index}: {exc}")
    return records, errors
