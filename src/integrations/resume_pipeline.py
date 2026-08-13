"""Structured bridge to the sibling resume-generation pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.database.db import get_project_root, load_settings

REQUEST_SCHEMA_VERSION = 1


@dataclass
class ResumeGenerationResult:
    request_id: str
    job_id: int
    status: str
    request_path: Path
    result_path: Path
    artifacts: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    agent_summary: str = ""

    @property
    def complete(self) -> bool:
        return self.status == "complete" and bool(self.artifacts.get("resume_docx"))

    @property
    def cover_letter_complete(self) -> bool:
        return self.status == "complete" and bool(self.artifacts.get("cover_letter_docx"))


def get_resume_pipeline_root(project_root: Path | None = None) -> Path:
    root = project_root or get_project_root()
    override = os.environ.get("RESUME_PIPELINE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    settings = load_settings()
    integrations = settings.get("integrations", {})
    resume = integrations.get("resume_pipeline", {}) if isinstance(integrations, dict) else {}
    configured = resume.get("repository", "../resume-generation-pipeline") if isinstance(resume, dict) else "../resume-generation-pipeline"
    return (root / str(configured)).resolve()


def create_resume_request(job: dict[str, Any], *, include_cover_letter: bool = False) -> tuple[Path, Path, dict[str, Any]]:
    root = get_project_root()
    request_id = f"resume-{int(job['job_id'])}-{uuid.uuid4().hex[:10]}"
    request_dir = root / "data" / "staging" / "resume_requests"
    result_dir = root / "data" / "staging" / "resume_results"
    request_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "job_id": int(job["job_id"]),
        "company": str(job.get("company_name") or "Unknown company"),
        "role": str(job.get("title") or "Target role"),
        "job_description": str(job.get("description") or ""),
        "source_url": str(job.get("url") or ""),
        "include_cover_letter": bool(include_cover_letter),
    }
    if not payload["job_description"].strip():
        raise ValueError("A stored job description is required before tailoring a resume.")

    request_path = request_dir / f"{request_id}.json"
    result_path = result_dir / f"{request_id}.json"
    request_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return request_path, result_path, payload


def create_cover_letter_request(job: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    """Create a cover-letter-only request using the established bridge schema."""
    request_path, result_path, payload = create_resume_request(job, include_cover_letter=True)
    old_request_id = payload["request_id"]
    request_id = old_request_id.replace("resume-", "cover-letter-", 1)
    payload["request_id"] = request_id
    payload["document_type"] = "cover_letter"
    new_request_path = request_path.with_name(f"{request_id}.json")
    new_result_path = result_path.with_name(f"{request_id}.json")
    request_path.unlink(missing_ok=True)
    new_request_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return new_request_path, new_result_path, payload


def run_resume_generation(
    job: dict[str, Any],
    *,
    include_cover_letter: bool = False,
    run_agent: bool = True,
    pipeline_root: Path | None = None,
) -> ResumeGenerationResult:
    request_path, result_path, request = create_resume_request(
        job, include_cover_letter=include_cover_letter
    )
    resume_root = pipeline_root or get_resume_pipeline_root()
    bridge_script = resume_root / "scripts" / "generate-application.py"
    if not bridge_script.is_file():
        raise FileNotFoundError(f"Resume pipeline bridge not found: {bridge_script}")

    settings = load_settings()
    integration = settings.get("integrations", {}).get("resume_pipeline", {})
    python = str(integration.get("python", "python3"))
    timeout = int(integration.get("timeout_seconds", 900))
    command = [
        python,
        str(bridge_script),
        "--request",
        str(request_path),
        "--result",
        str(result_path),
        "--timeout",
        str(timeout),
    ]
    if run_agent:
        command.append("--run-agent")

    completed = subprocess.run(
        command,
        cwd=resume_root,
        text=True,
        capture_output=True,
        timeout=timeout + 30,
        check=False,
    )
    if not result_path.is_file():
        message = completed.stderr.strip() or completed.stdout.strip() or "Resume bridge produced no result."
        raise RuntimeError(message)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    warnings = [str(item) for item in result.get("warnings", [])]
    if completed.returncode != 0 and not warnings:
        warnings.append(completed.stderr.strip() or f"Resume bridge exited with {completed.returncode}")

    artifacts = dict(result.get("artifacts") or {})
    _discover_cover_letter_artifacts(artifacts)
    return ResumeGenerationResult(
        request_id=str(result.get("request_id") or request["request_id"]),
        job_id=int(result.get("job_id") or request["job_id"]),
        status=str(result.get("status") or "failed"),
        request_path=request_path,
        result_path=result_path,
        artifacts=artifacts,
        warnings=warnings,
        agent_summary=str(result.get("agent_summary") or ""),
    )


def run_cover_letter_generation(
    job: dict[str, Any],
    *,
    run_agent: bool = True,
    pipeline_root: Path | None = None,
) -> ResumeGenerationResult:
    """Run the cover-letter-only pipeline without generating or validating a resume."""
    request_path, result_path, request = create_cover_letter_request(job)
    resume_root = pipeline_root or get_resume_pipeline_root()
    bridge_script = resume_root / "scripts" / "generate-cover-letter.py"
    if not bridge_script.is_file():
        raise FileNotFoundError(f"Cover letter pipeline bridge not found: {bridge_script}")

    settings = load_settings()
    integration = settings.get("integrations", {}).get("resume_pipeline", {})
    python = str(integration.get("python", "python3"))
    timeout = int(integration.get("timeout_seconds", 900))
    command = [
        python,
        str(bridge_script),
        "--request",
        str(request_path),
        "--result",
        str(result_path),
        "--timeout",
        str(timeout),
    ]
    if run_agent:
        command.append("--run-agent")

    completed = subprocess.run(
        command,
        cwd=resume_root,
        text=True,
        capture_output=True,
        timeout=timeout + 30,
        check=False,
    )
    if not result_path.is_file():
        message = completed.stderr.strip() or completed.stdout.strip() or "Cover letter bridge produced no result."
        raise RuntimeError(message)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    warnings = [str(item) for item in result.get("warnings", [])]
    if completed.returncode != 0 and not warnings:
        warnings.append(completed.stderr.strip() or f"Cover letter bridge exited with {completed.returncode}")
    artifacts = dict(result.get("artifacts") or {})
    _discover_cover_letter_artifacts(artifacts)
    return ResumeGenerationResult(
        request_id=str(result.get("request_id") or request["request_id"]),
        job_id=int(result.get("job_id") or request["job_id"]),
        status=str(result.get("status") or "failed"),
        request_path=request_path,
        result_path=result_path,
        artifacts=artifacts,
        warnings=warnings,
        agent_summary=str(result.get("agent_summary") or ""),
    )


def format_resume_step_details(result: ResumeGenerationResult) -> str:
    lines = [f"Request: {result.request_id}", f"Status: {result.status}"]
    labels = {
        "resume_docx": "Resume DOCX",
        "resume_markdown": "Resume draft",
        "cover_letter_docx": "Cover letter DOCX",
        "cover_letter_markdown": "Cover letter draft",
        "analysis": "Application analysis",
        "application_dir": "Application folder",
    }
    for key, label in labels.items():
        if result.artifacts.get(key):
            lines.append(f"{label}: {result.artifacts[key]}")
    if result.warnings:
        lines.append("Warnings: " + " | ".join(result.warnings))
    return "\n".join(lines)


def _discover_cover_letter_artifacts(artifacts: dict[str, Any]) -> None:
    """Backfill cover-letter paths returned by older bridge script versions."""
    application_dir = Path(str(artifacts.get("application_dir") or "")).expanduser()
    if not application_dir.is_dir():
        return
    markdown = application_dir / "cover-letter.md"
    if markdown.is_file() and not artifacts.get("cover_letter_markdown"):
        artifacts["cover_letter_markdown"] = str(markdown.resolve())
    output_dir = application_dir / "output"
    documents = sorted(output_dir.glob("CoverLetter_*.docx")) if output_dir.is_dir() else []
    if documents and not artifacts.get("cover_letter_docx"):
        artifacts["cover_letter_docx"] = str(documents[-1].resolve())
