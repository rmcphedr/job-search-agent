"""Tests for the cross-repository resume bridge adapter."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.integrations.resume_pipeline import (
    format_resume_step_details,
    run_cover_letter_generation,
    run_resume_generation,
)


def test_resume_bridge_writes_request_and_loads_result(tmp_path: Path, monkeypatch) -> None:
    job_root = tmp_path / "job-search-agent"
    resume_root = tmp_path / "resume-generation-pipeline"
    bridge = resume_root / "scripts" / "generate-application.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("# bridge fixture\n", encoding="utf-8")

    monkeypatch.setattr("src.integrations.resume_pipeline.get_project_root", lambda: job_root)
    monkeypatch.setattr(
        "src.integrations.resume_pipeline.load_settings",
        lambda: {
            "integrations": {
                "resume_pipeline": {
                    "repository": str(resume_root),
                    "python": "python3",
                    "timeout_seconds": 30,
                }
            }
        },
    )

    def fake_run(command, **kwargs):
        request_path = Path(command[command.index("--request") + 1])
        result_path = Path(command[command.index("--result") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "request_id": request["request_id"],
                    "job_id": request["job_id"],
                    "status": "complete",
                    "artifacts": {"resume_docx": "/tmp/resume.docx"},
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("src.integrations.resume_pipeline.subprocess.run", fake_run)
    result = run_resume_generation(
        {
            "job_id": 42,
            "company_name": "Example Bio",
            "title": "ML Scientist",
            "description": "Build validated machine-learning systems.",
            "url": "https://example.com/jobs/42",
        },
        pipeline_root=resume_root,
    )

    assert result.complete is True
    request = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert request["schema_version"] == 1
    assert request["job_id"] == 42
    assert request["company"] == "Example Bio"


def test_resume_bridge_requires_a_job_description(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.integrations.resume_pipeline.get_project_root", lambda: tmp_path)
    try:
        run_resume_generation(
            {"job_id": 5, "company_name": "Example", "title": "Scientist", "description": ""},
            pipeline_root=tmp_path,
        )
    except ValueError as exc:
        assert "job description" in str(exc).lower()
    else:
        raise AssertionError("Expected a missing-description error")


def test_cover_letter_request_discovers_legacy_bridge_artifacts(tmp_path: Path, monkeypatch) -> None:
    job_root = tmp_path / "job-search-agent"
    resume_root = tmp_path / "resume-generation-pipeline"
    bridge = resume_root / "scripts" / "generate-cover-letter.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("# bridge fixture\n", encoding="utf-8")
    application_dir = resume_root / "applications" / "example"
    output_dir = application_dir / "output"
    output_dir.mkdir(parents=True)
    (application_dir / "cover-letter.md").write_text("# Letter\n", encoding="utf-8")
    cover_letter = output_dir / "CoverLetter_Role_Company_10-08-2026.docx"
    cover_letter.write_bytes(b"docx fixture")

    monkeypatch.setattr("src.integrations.resume_pipeline.get_project_root", lambda: job_root)
    monkeypatch.setattr(
        "src.integrations.resume_pipeline.load_settings",
        lambda: {"integrations": {"resume_pipeline": {"python": "python3", "timeout_seconds": 30}}},
    )

    def fake_run(command, **kwargs):
        request_path = Path(command[command.index("--request") + 1])
        result_path = Path(command[command.index("--result") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        assert request["include_cover_letter"] is True
        result_path.write_text(
            json.dumps(
                {
                    "request_id": request["request_id"],
                    "job_id": request["job_id"],
                    "status": "complete",
                    "artifacts": {
                        "application_dir": str(application_dir),
                        "resume_docx": "/tmp/resume.docx",
                    },
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("src.integrations.resume_pipeline.subprocess.run", fake_run)
    result = run_cover_letter_generation(
        {
            "job_id": 7,
            "company_name": "Example",
            "title": "Role",
            "description": "Build systems.",
        },
        pipeline_root=resume_root,
    )

    assert result.cover_letter_complete
    assert result.artifacts["cover_letter_docx"] == str(cover_letter.resolve())
    assert "Cover letter DOCX:" in format_resume_step_details(result)
    request = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert request["document_type"] == "cover_letter"
    assert result.request_id.startswith("cover-letter-")
