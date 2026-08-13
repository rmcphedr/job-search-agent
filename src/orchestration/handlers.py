"""Merge handlers: validate staging files and write canonical stores."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.database.db import get_connection
from src.database.migrate import apply_migrations
from src.discovery.models import CompanyCandidate
from src.discovery.update_inventory import get_inventory_path, update_inventory
from src.llm.schemas import CompanyFitResult, JobFitResult
from src.orchestration.evaluation_store import has_company_evaluation, upsert_company_evaluation
from src.orchestration.events import emit_event
from src.orchestration.manifest import (
    RunManifest,
    is_file_processed,
    load_manifest,
    mark_file_processed,
    save_manifest,
)
from src.orchestration.paths import infer_run_id_from_path, rejected_dir
from src.validators import load_staging_records

logger = logging.getLogger(__name__)


@dataclass
class MergeResult:
    success: bool
    action: str
    company_name: str | None = None
    company_id: int | None = None
    job_id: int | None = None
    records_merged: int | None = None
    run_id: str | None = None
    errors: list[str] | None = None
    event_emitted: str | None = None
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action,
            "company_name": self.company_name,
            "company_id": self.company_id,
            "job_id": self.job_id,
            "records_merged": self.records_merged,
            "run_id": self.run_id,
            "errors": self.errors,
            "event_emitted": self.event_emitted,
            "skipped_reason": self.skipped_reason,
        }


def _record_sqlite_run(run_type: str, notes: dict[str, Any]) -> None:
    try:
        connection = get_connection()
        try:
            connection.execute(
                """
                INSERT INTO runs (run_type, started_at, completed_at, companies_checked, notes)
                VALUES (?, datetime('now'), datetime('now'), ?, ?);
                """,
                (
                    run_type,
                    notes.get("companies_checked", 0),
                    json.dumps(notes),
                ),
            )
            connection.commit()
        finally:
            connection.close()
    except Exception as exc:
        logger.warning("Failed to record SQLite run: %s", exc)


def _lookup_company_id(company_name: str) -> int | None:
    path = get_inventory_path()
    if not path.exists():
        return None
    frame = pd.read_csv(path, dtype=str)
    if frame.empty:
        return None
    normalized = company_name.strip().lower()
    matches = frame[frame["company_name"].fillna("").str.strip().str.lower() == normalized]
    if matches.empty:
        return None
    try:
        return int(matches.iloc[-1]["company_id"])
    except (TypeError, ValueError):
        return None


def _company_exists_before_merge(company_name: str) -> bool:
    return _lookup_company_id(company_name) is not None


def _reject_file(path: Path, errors: list[str], run_id: str | None) -> None:
    if run_id is None:
        run_id = infer_run_id_from_path(path) or "unknown"
    destination_dir = rejected_dir(run_id)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / path.name
    shutil.move(str(path), str(destination))
    sidecar = destination.with_suffix(destination.suffix + ".error.json")
    sidecar.write_text(json.dumps({"errors": errors}, indent=2), encoding="utf-8")


def _update_manifest_counts(run_id: str | None, **increments: int) -> None:
    if not run_id:
        return
    manifest = load_manifest(run_id)
    if manifest is None:
        return
    for field, amount in increments.items():
        if hasattr(manifest.counts, field):
            current = getattr(manifest.counts, field)
            setattr(manifest.counts, field, current + amount)
    save_manifest(manifest)


def merge_company_candidate_file(
    path: Path,
    *,
    emit_events: bool = True,
    delete_on_success: bool = False,
) -> MergeResult:
    """Validate and merge one company candidate staging file into inventory."""
    run_id = infer_run_id_from_path(path)
    records, errors = load_staging_records(path, CompanyCandidate)
    if errors or not records:
        if path.exists():
            _reject_file(path, errors or ["No valid CompanyCandidate records"], run_id)
        _update_manifest_counts(run_id, candidates_rejected=1)
        if emit_events:
            emit_event(
                "candidate.rejected",
                run_id=run_id,
                payload={"path": str(path), "errors": errors},
            )
        return MergeResult(
            success=False,
            action="reject",
            run_id=run_id,
            errors=errors or ["No valid records"],
        )

    candidate = records[0]
    existed_before = _company_exists_before_merge(candidate.company_name)

    result = update_inventory([candidate])
    company_id = _lookup_company_id(candidate.company_name)

    if result.inserted > 0:
        action = "insert"
        _update_manifest_counts(run_id, candidates_merged=1)
        event_type = "company.merged"
    elif result.updated_fields > 0:
        action = "update"
        _update_manifest_counts(run_id, candidates_duplicate=1)
        event_type = None
    else:
        action = "duplicate"
        _update_manifest_counts(run_id, candidates_duplicate=1)
        event_type = None

    event_emitted: str | None = None
    if emit_events:
        emit_event(
            "candidate.staged",
            run_id=run_id,
            payload={
                "path": str(path),
                "company_name": candidate.company_name,
                "action": action,
            },
        )
        if event_type == "company.merged" and company_id is not None:
            event = emit_event(
                "company.merged",
                run_id=run_id,
                payload={
                    "company_id": company_id,
                    "company_name": candidate.company_name,
                    "staging_path": str(path),
                    "inserted": not existed_before,
                },
            )
            event_emitted = event.type
            _record_sqlite_run(
                "staging_merge_candidate",
                {
                    "companies_checked": 1,
                    "company_name": candidate.company_name,
                    "company_id": company_id,
                    "run_id": run_id,
                    "action": action,
                },
            )

    if run_id:
        manifest = load_manifest(run_id)
        if manifest:
            mark_file_processed(manifest, path)
            save_manifest(manifest)

    if delete_on_success and path.exists() and action in {"insert", "update", "duplicate"}:
        path.unlink(missing_ok=True)

    return MergeResult(
        success=True,
        action=action,
        company_name=candidate.company_name,
        company_id=company_id,
        run_id=run_id,
        event_emitted=event_emitted,
        skipped_reason=None if event_type else "duplicate_or_update",
    )


def merge_company_evaluation_file(
    path: Path,
    *,
    force_re_eval: bool = False,
    emit_events: bool = True,
    delete_on_success: bool = False,
) -> MergeResult:
    """Validate and merge one company evaluation staging file into canonical CSV."""
    run_id = infer_run_id_from_path(path)
    records, errors = load_staging_records(path, CompanyFitResult)
    if errors or not records:
        if path.exists():
            _reject_file(path, errors or ["No valid CompanyFitResult records"], run_id)
        _update_manifest_counts(run_id, evaluations_rejected=1)
        if emit_events:
            emit_event(
                "evaluation.rejected",
                run_id=run_id,
                payload={"path": str(path), "errors": errors},
            )
        return MergeResult(
            success=False,
            action="reject",
            run_id=run_id,
            errors=errors or ["No valid records"],
        )

    evaluation = records[0]
    if has_company_evaluation(evaluation.company_name) and not force_re_eval:
        _update_manifest_counts(run_id, evaluations_skipped=1)
        if emit_events:
            emit_event(
                "evaluation.skipped",
                run_id=run_id,
                payload={
                    "company_name": evaluation.company_name,
                    "reason": "already_evaluated",
                    "path": str(path),
                },
            )
        if run_id:
            manifest = load_manifest(run_id)
            if manifest:
                mark_file_processed(manifest, path)
                save_manifest(manifest)
        return MergeResult(
            success=True,
            action="skip",
            company_name=evaluation.company_name,
            run_id=run_id,
            skipped_reason="already_evaluated",
        )

    upsert_company_evaluation(
        evaluation,
        run_id=run_id,
        source_path=str(path),
    )
    _update_manifest_counts(run_id, evaluations_merged=1)

    event_emitted: str | None = None
    if emit_events:
        emit_event(
            "evaluation.staged",
            run_id=run_id,
            payload={
                "path": str(path),
                "company_name": evaluation.company_name,
            },
        )
        event = emit_event(
            "evaluation.merged",
            run_id=run_id,
            payload={
                "company_name": evaluation.company_name,
                "fit_score": evaluation.fit_score,
                "staging_path": str(path),
            },
        )
        event_emitted = event.type
        _record_sqlite_run(
            "staging_merge_evaluation",
            {
                "companies_checked": 1,
                "company_name": evaluation.company_name,
                "fit_score": evaluation.fit_score,
                "run_id": run_id,
            },
        )

    if run_id:
        manifest = load_manifest(run_id)
        if manifest:
            mark_file_processed(manifest, path)
            save_manifest(manifest)

    if delete_on_success and path.exists():
        path.unlink(missing_ok=True)

    return MergeResult(
        success=True,
        action="merge",
        company_name=evaluation.company_name,
        run_id=run_id,
        event_emitted=event_emitted,
    )


def merge_job_evaluation_file(path: Path, *, emit_events: bool = True) -> MergeResult:
    """Validate job evaluations and atomically merge them into SQLite by job_id."""
    run_id = infer_run_id_from_path(path)
    records, errors = load_staging_records(path, JobFitResult)
    if errors or not records:
        return MergeResult(
            success=False,
            action="reject",
            run_id=run_id,
            errors=errors or ["No valid JobFitResult records"],
        )

    missing_ids = [record.job_title for record in records if record.job_id is None]
    if missing_ids:
        return MergeResult(
            success=False,
            action="reject",
            run_id=run_id,
            errors=[f"job_id is required for SQLite merge: {title}" for title in missing_ids],
        )

    connection = get_connection()
    try:
        apply_migrations(connection)
        for record in records:
            row = connection.execute(
                """
                SELECT j.title, c.company_name, j.description_status, j.description_checked_at
                FROM job_postings AS j
                JOIN companies AS c ON c.company_id = j.company_id
                WHERE j.job_id = ? AND j.active = 1;
                """,
                (record.job_id,),
            ).fetchone()
            if row is None:
                errors.append(f"Active job not found: job_id={record.job_id}")
                continue
            if row["title"].strip() != record.job_title.strip():
                errors.append(
                    f"job_id={record.job_id} title mismatch: database={row['title']!r}, evaluation={record.job_title!r}"
                )
            if row["company_name"].strip() != record.company_name.strip():
                errors.append(
                    f"job_id={record.job_id} company mismatch: database={row['company_name']!r}, evaluation={record.company_name!r}"
                )
            if row["description_status"] != "enriched" or not row["description_checked_at"]:
                errors.append(
                    f"job_id={record.job_id} must have a current verified description before evaluation"
                )

        if errors:
            return MergeResult(success=False, action="reject", run_id=run_id, errors=errors)

        for record in records:
            connection.execute(
                """
                UPDATE job_postings
                SET fit_score = ?, fit_reason = ?, fit_details = ?, evaluated_at = datetime('now')
                WHERE job_id = ?;
                """,
                (
                    record.fit_score,
                    record.why_fit,
                    record.model_dump_json(),
                    record.job_id,
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    if emit_events:
        for record in records:
            emit_event(
                "job.evaluation.merged",
                run_id=run_id,
                payload={
                    "job_id": record.job_id,
                    "job_title": record.job_title,
                    "company_name": record.company_name,
                    "fit_score": record.fit_score,
                    "staging_path": str(path),
                },
            )
        _record_sqlite_run(
            "staging_merge_job_evaluations",
            {
                "jobs_checked": len(records),
                "job_ids": [record.job_id for record in records],
                "run_id": run_id,
            },
        )

    return MergeResult(
        success=True,
        action="merge",
        run_id=run_id,
        records_merged=len(records),
    )


def merge_staging_file(path: Path, *, force_re_eval: bool = False) -> MergeResult:
    """Route a staging file to the correct merge handler based on path/schema."""
    path = path.resolve()
    if not path.exists():
        return MergeResult(success=False, action="missing", errors=[f"File not found: {path}"])

    parent = path.parent.name.lower()
    if parent == "company_candidates" or path.stem.lower().startswith("company_candidates"):
        return merge_company_candidate_file(path)
    if parent == "company_evaluations" or path.stem.lower().startswith("company_evaluations"):
        return merge_company_evaluation_file(path, force_re_eval=force_re_eval)
    if parent == "job_evaluations" or path.stem.lower().startswith("job_evaluations"):
        return merge_job_evaluation_file(path)

    records, errors = load_staging_records(path)
    if errors:
        return MergeResult(success=False, action="reject", errors=errors)
    if not records:
        return MergeResult(success=False, action="reject", errors=["No records and unknown schema"])

    first = records[0]
    if isinstance(first, CompanyCandidate):
        return merge_company_candidate_file(path)
    if isinstance(first, CompanyFitResult):
        return merge_company_evaluation_file(path, force_re_eval=force_re_eval)
    if isinstance(first, JobFitResult):
        return merge_job_evaluation_file(path)

    return MergeResult(success=False, action="reject", errors=[f"Unsupported staging file: {path}"])


def merge_run_directory(
    run_id: str,
    *,
    force_re_eval: bool = False,
) -> list[MergeResult]:
    """Process all unprocessed staging files under a run directory."""
    manifest = load_manifest(run_id)
    results: list[MergeResult] = []

    from src.orchestration.paths import candidates_dir, evaluations_dir, run_dir

    base = run_dir(run_id)
    if not base.exists():
        return [MergeResult(success=False, action="missing", errors=[f"Run not found: {run_id}"])]

    candidate_files = sorted(candidates_dir(run_id).glob("*.json"))
    evaluation_files = sorted(evaluations_dir(run_id).glob("*.json"))

    for file_path in candidate_files:
        if manifest and is_file_processed(manifest, file_path):
            continue
        results.append(merge_staging_file(file_path))

    for file_path in evaluation_files:
        if manifest and is_file_processed(manifest, file_path):
            continue
        results.append(merge_staging_file(file_path, force_re_eval=force_re_eval))

    if manifest:
        manifest = load_manifest(run_id)
        if manifest:
            save_manifest(manifest)

    return results
