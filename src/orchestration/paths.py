"""Path helpers for run-scoped staging directories."""

from __future__ import annotations

import re
from pathlib import Path

from src.database.db import get_project_root, load_settings


def get_staging_root() -> Path:
    try:
        settings = load_settings()
        paths = settings.get("paths", {})
        if isinstance(paths, dict):
            staging = paths.get("staging")
            if isinstance(staging, str) and staging.strip():
                return get_project_root() / staging
    except RuntimeError:
        pass
    return get_project_root() / "data" / "staging"


def get_runs_root() -> Path:
    return get_staging_root() / "runs"


def get_events_dir() -> Path:
    try:
        settings = load_settings()
        paths = settings.get("paths", {})
        if isinstance(paths, dict):
            events = paths.get("events")
            if isinstance(events, str) and events.strip():
                return get_project_root() / events
    except RuntimeError:
        pass
    return get_project_root() / "data" / "events"


def run_dir(run_id: str) -> Path:
    return get_runs_root() / run_id


def candidates_dir(run_id: str) -> Path:
    return run_dir(run_id) / "company_candidates"


def evaluations_dir(run_id: str) -> Path:
    return run_dir(run_id) / "company_evaluations"


def rejected_dir(run_id: str) -> Path:
    return run_dir(run_id) / "rejected"


def manifest_path(run_id: str) -> Path:
    return run_dir(run_id) / "manifest.json"


def slugify_company_name(name: str) -> str:
    """Create a filesystem-safe slug from a company name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "company"


def infer_run_id_from_path(path: Path) -> str | None:
    """Extract run_id when path is under data/staging/runs/<run_id>/..."""
    try:
        parts = path.resolve().parts
        runs_idx = parts.index("runs")
        return parts[runs_idx + 1]
    except (ValueError, IndexError):
        return None
