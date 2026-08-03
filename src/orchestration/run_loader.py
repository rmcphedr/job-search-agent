"""Load latest Hermes run manifests for dashboard display."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.orchestration.manifest import RunManifest, load_manifest
from src.orchestration.paths import get_runs_root


def list_run_ids() -> list[str]:
    root = get_runs_root()
    if not root.exists():
        return []
    run_ids = [path.name for path in root.iterdir() if path.is_dir() and (path / "manifest.json").exists()]
    return sorted(run_ids, reverse=True)


def load_latest_run_manifest() -> RunManifest | None:
    run_ids = list_run_ids()
    if not run_ids:
        return None
    return load_manifest(run_ids[0])


def load_run_summaries(limit: int = 10) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for run_id in list_run_ids()[:limit]:
        manifest = load_manifest(run_id)
        if manifest is None:
            continue
        summaries.append(
            {
                "run_id": manifest.run_id,
                "status": manifest.status,
                "started_at": manifest.started_at,
                "completed_at": manifest.completed_at,
                "request": manifest.request,
                "counts": manifest.counts.__dict__,
            }
        )
    return summaries


def load_calibration_summary(run_id: str) -> dict[str, Any] | None:
    from src.orchestration.calibration import load_calibration

    calibration = load_calibration(run_id)
    if calibration is None:
        return None
    return {
        "corrections": len(calibration.corrections),
        "preference_updates": calibration.preference_updates,
        "applied_to_evaluations": calibration.applied_to_evaluations,
        "applied_to_profile": calibration.applied_to_profile,
    }
