"""Tests for staging validation, merge, and event log."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.discovery.models import CompanyCandidate
from src.orchestration.evaluation_store import (
    company_evaluations_path,
    has_company_evaluation,
    upsert_company_evaluation,
)
from src.orchestration.events import emit_event, read_events_since
from src.orchestration.handlers import merge_company_candidate_file, merge_company_evaluation_file
from src.orchestration.manifest import create_run_manifest, load_manifest
from src.llm.schemas import CompanyFitResult
from src.validators import load_staging_records


@pytest.fixture
def temp_project(tmp_path, monkeypatch):
    """Isolate inventory, evaluations, and events under tmp_path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    events_dir = data_dir / "events"
    events_dir.mkdir()
    staging_dir = data_dir / "staging"
    staging_dir.mkdir()
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()

    inventory = data_dir / "company_inventory.csv"
    inventory.write_text(
        "company_id,company_name,website,industry,location,size,hiring_status,priority,"
        "last_checked,source_id,source_url,source_category,confidence,notes\n",
        encoding="utf-8",
    )

    settings = {
        "paths": {
            "company_inventory": "data/company_inventory.csv",
            "company_evaluations": "data/company_evaluations.csv",
            "staging": "data/staging",
            "events": "data/events",
            "outputs": "outputs",
        }
    }
    settings_path = tmp_path / "config"
    settings_path.mkdir()
    import yaml

    (settings_path / "settings.yaml").write_text(yaml.dump(settings), encoding="utf-8")

    from src.database import db as db_module
    from src.discovery import update_inventory as inventory_module
    from src.orchestration import paths as paths_module
    from src.orchestration import evaluation_store as eval_module

    def _root() -> Path:
        return tmp_path

    monkeypatch.setattr(db_module, "get_project_root", _root)
    monkeypatch.setattr(inventory_module, "get_project_root", _root)
    monkeypatch.setattr(paths_module, "get_project_root", _root)
    monkeypatch.setattr(eval_module, "get_project_root", _root)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_load_staging_single_object(tmp_path):
    path = tmp_path / "company_candidates" / "acme.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "company_name": "Acme Health AI",
                "website": "https://acmehealth.ai",
                "source_id": "test",
                "source_name": "Test",
                "source_url": "https://example.com",
                "confidence": 0.8,
            }
        ),
        encoding="utf-8",
    )
    records, errors = load_staging_records(path, CompanyCandidate)
    assert not errors
    assert len(records) == 1
    assert records[0].company_name == "Acme Health AI"


def test_create_run_manifest(temp_project):
    manifest = create_run_manifest("20260801T120000Z", request={"count": 5})
    assert manifest.run_id == "20260801T120000Z"
    assert manifest.request["count"] == 5
    loaded = load_manifest("20260801T120000Z")
    assert loaded is not None
    assert loaded.status == "running"


def test_emit_and_read_events(temp_project):
    log_path = temp_project / "data" / "events" / "test_log.jsonl"
    event = emit_event("test.event", run_id="run-1", payload={"foo": "bar"}, log_path=log_path)
    events = read_events_since(event_types={"test.event"}, log_path=log_path)
    assert len(events) == 1
    assert events[0].payload["foo"] == "bar"


def test_merge_company_candidate_inserts_and_emits_event(temp_project):
    run_id = "20260801T120000Z"
    create_run_manifest(run_id)
    candidate_path = (
        temp_project
        / "data"
        / "staging"
        / "runs"
        / run_id
        / "company_candidates"
        / "acme-health-ai.json"
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
            json.dumps(
                {
                    "company_name": "Zephyr Staging Test Co",
                    "website": "https://zephyr-staging-test.example",
                    "source_id": "test",
                    "source_name": "Test Source",
                    "source_url": "https://example.com/zephyr",
                    "source_category": "AI healthcare",
                    "confidence": 0.85,
                    "notes": "Test candidate",
                }
            ),
        encoding="utf-8",
    )

    result = merge_company_candidate_file(candidate_path)
    assert result.success
    assert result.action == "insert"
    assert result.event_emitted == "company.merged"

    inventory = pd.read_csv(temp_project / "data" / "company_inventory.csv")
    assert "Zephyr Staging Test Co" in inventory["company_name"].values

    events = read_events_since(event_types={"company.merged"}, run_id=run_id, log_path=temp_project / "data" / "events" / "event_log.jsonl")
    assert len(events) == 1
    assert events[0].payload["company_name"] == "Zephyr Staging Test Co"


def test_merge_evaluation_skips_without_force_re_eval(temp_project):
    run_id = "20260801T120000Z"
    create_run_manifest(run_id)

    evaluation = CompanyFitResult(
        company_name="Existing Co",
        fit_score=7.0,
        industry_alignment=7.0,
        mission_alignment=7.0,
        career_alignment=7.0,
        growth_potential=7.0,
        reasoning="Already evaluated.",
        confidence=7.0,
    )
    upsert_company_evaluation(evaluation, run_id="prior-run")

    eval_path = (
        temp_project
        / "data"
        / "staging"
        / "runs"
        / run_id
        / "company_evaluations"
        / "existing-co.json"
    )
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    eval_path.write_text(evaluation.model_dump_json(), encoding="utf-8")

    result = merge_company_evaluation_file(eval_path, force_re_eval=False)
    assert result.success
    assert result.action == "skip"
    assert result.skipped_reason == "already_evaluated"
    assert has_company_evaluation("Existing Co")


def test_merge_evaluation_with_force_re_eval(temp_project):
    run_id = "20260801T120000Z"
    create_run_manifest(run_id)

    evaluation = CompanyFitResult(
        company_name="Refresh Co",
        fit_score=6.0,
        industry_alignment=6.0,
        mission_alignment=6.0,
        career_alignment=6.0,
        growth_potential=6.0,
        reasoning="First pass.",
        confidence=6.0,
    )
    upsert_company_evaluation(evaluation, run_id="prior-run")

    updated = evaluation.model_copy(update={"fit_score": 8.5, "reasoning": "Updated after user request."})
    eval_path = (
        temp_project
        / "data"
        / "staging"
        / "runs"
        / run_id
        / "company_evaluations"
        / "refresh-co.json"
    )
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    eval_path.write_text(updated.model_dump_json(), encoding="utf-8")

    result = merge_company_evaluation_file(eval_path, force_re_eval=True)
    assert result.success
    assert result.action == "merge"

    frame = pd.read_csv(company_evaluations_path())
    row = frame[frame["company_name"] == "Refresh Co"].iloc[-1]
    assert float(row["fit_score"]) == 8.5
