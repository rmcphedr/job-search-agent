"""Run manifest CRUD for Hermes-orchestrated discovery runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.orchestration.paths import manifest_path, run_dir


@dataclass
class RunCounts:
    candidates_staged: int = 0
    candidates_merged: int = 0
    candidates_rejected: int = 0
    candidates_duplicate: int = 0
    evaluations_staged: int = 0
    evaluations_merged: int = 0
    evaluations_skipped: int = 0
    evaluations_rejected: int = 0


@dataclass
class RunManifest:
    run_id: str
    type: str = "company_discovery_evaluation"
    requested_by: str = "hermes"
    request: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    counts: RunCounts = field(default_factory=RunCounts)
    processed_staging_files: list[str] = field(default_factory=list)
    last_event_id: str | None = None
    started_at: str = ""
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["counts"] = asdict(self.counts)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunManifest:
        counts_data = data.get("counts", {})
        counts = RunCounts(**counts_data) if isinstance(counts_data, dict) else RunCounts()
        return cls(
            run_id=data["run_id"],
            type=data.get("type", "company_discovery_evaluation"),
            requested_by=data.get("requested_by", "hermes"),
            request=data.get("request", {}),
            status=data.get("status", "running"),
            counts=counts,
            processed_staging_files=list(data.get("processed_staging_files", [])),
            last_event_id=data.get("last_event_id"),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at"),
        )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def create_run_manifest(
    run_id: str,
    *,
    request: dict[str, Any] | None = None,
    requested_by: str = "hermes",
) -> RunManifest:
    """Create run directory and initial manifest."""
    directory = run_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "company_candidates").mkdir(exist_ok=True)
    (directory / "company_evaluations").mkdir(exist_ok=True)
    (directory / "rejected").mkdir(exist_ok=True)

    manifest = RunManifest(
        run_id=run_id,
        request=request or {},
        requested_by=requested_by,
        status="running",
        started_at=_utc_now(),
    )
    save_manifest(manifest)
    return manifest


def load_manifest(run_id: str) -> RunManifest | None:
    path = manifest_path(run_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunManifest.from_dict(data)


def save_manifest(manifest: RunManifest) -> Path:
    path = manifest_path(manifest.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return path


def mark_file_processed(manifest: RunManifest, staging_path: Path) -> None:
    key = str(staging_path.resolve())
    if key not in manifest.processed_staging_files:
        manifest.processed_staging_files.append(key)


def is_file_processed(manifest: RunManifest, staging_path: Path) -> bool:
    return str(staging_path.resolve()) in manifest.processed_staging_files
