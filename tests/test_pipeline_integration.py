"""Integration tests for staging watcher → merge → evaluation → calibration."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.discovery.models import CompanyCandidate
from src.llm.schemas import CompanyFitResult
from src.orchestration.apply_preferences import apply_profile_updates
from src.orchestration.calibration import apply_calibration_to_evaluations, load_calibration
from src.orchestration.calibration_models import CalibrationCorrection, CalibrationFile
from src.orchestration.evaluation_store import company_evaluations_path, load_company_evaluations
from src.orchestration.handlers import merge_staging_file
from src.orchestration.manifest import create_run_manifest
from src.orchestration.watch_staging import StagingMergeHandler


@pytest.fixture
def temp_project(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "events").mkdir()
    staging_dir = data_dir / "staging"
    staging_dir.mkdir()
    (tmp_path / "outputs").mkdir()

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
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    import yaml

    (config_dir / "settings.yaml").write_text(yaml.dump(settings), encoding="utf-8")
    (tmp_path / "user").mkdir()
    (tmp_path / "user" / "agent_calibration.md").write_text("# Agent calibration notes\n\n", encoding="utf-8")

    from src.database import db as db_module
    from src.discovery import update_inventory as inventory_module
    from src.orchestration import paths as paths_module
    from src.orchestration import evaluation_store as eval_module
    from src.orchestration import apply_preferences as prefs_module

    def _root() -> Path:
        return tmp_path

    for module in (db_module, inventory_module, paths_module, eval_module, prefs_module):
        monkeypatch.setattr(module, "get_project_root", _root)

    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_end_to_end_run_with_watcher_and_calibration(temp_project):
    run_id = "integration20260801T120000Z"
    create_run_manifest(run_id, request={"count": 1})

    candidate_path = (
        temp_project
        / "data"
        / "staging"
        / "runs"
        / run_id
        / "company_candidates"
        / "integration-test-co.json"
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate = CompanyCandidate(
        company_name="Integration Test Co",
        website="https://integration-test.example",
        source_id="integration_test",
        source_name="Integration test",
        source_url="https://example.com/integration",
        source_category="AI healthcare",
        confidence=0.9,
        notes="integration pipeline",
    )
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")

    handler = StagingMergeHandler(settle_seconds=0)
    handler._schedule(candidate_path)
    handler.process_pending()

    inventory = pd.read_csv(temp_project / "data" / "company_inventory.csv")
    assert "Integration Test Co" in inventory["company_name"].values

    evaluation = CompanyFitResult(
        company_name="Integration Test Co",
        fit_score=8.0,
        industry_alignment=8.0,
        mission_alignment=7.5,
        career_alignment=8.0,
        growth_potential=7.0,
        reasoning="Strong integration test fit.",
        best_roles=["ML Scientist"],
        interesting_factors=["healthcare AI"],
        red_flags=[],
        confidence=7.5,
    )
    eval_path = (
        temp_project
        / "data"
        / "staging"
        / "runs"
        / run_id
        / "company_evaluations"
        / "integration-test-co.json"
    )
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    eval_path.write_text(evaluation.model_dump_json(), encoding="utf-8")

    handler._schedule(eval_path)
    handler.process_pending()

    evaluations = load_company_evaluations(company_evaluations_path())
    assert not evaluations.empty
    row = evaluations[evaluations["company_name"] == "Integration Test Co"].iloc[-1]
    assert float(row["fit_score"]) == 8.0

    calibration_path = temp_project / "data" / "staging" / "runs" / run_id / "calibration.json"
    calibration = CalibrationFile(
        corrections=[
            CalibrationCorrection(
                company_name="Integration Test Co",
                original_fit_score=8.0,
                corrected_fit_score=6.5,
                feedback="Prefer product companies over services.",
            )
        ],
        preference_updates=["Weight product focus over consulting revenue"],
    )
    calibration_path.write_text(calibration.model_dump_json(indent=2), encoding="utf-8")

    apply_result = apply_calibration_to_evaluations(run_id)
    assert apply_result.corrections_applied == 1

    evaluations = load_company_evaluations(company_evaluations_path())
    row = evaluations[evaluations["company_name"] == "Integration Test Co"].iloc[-1]
    assert float(row["fit_score"]) == 6.5
    assert float(row["original_fit_score"]) == 8.0

    dry_run = apply_profile_updates(run_id, confirm=False)
    assert dry_run["dry_run"] is True

    applied = apply_profile_updates(run_id, confirm=True)
    assert applied["success"] is True
    assert "product focus" in (temp_project / "user" / "agent_calibration.md").read_text(encoding="utf-8")

    saved = load_calibration(run_id)
    assert saved is not None
    assert saved.applied_to_profile is True
    assert saved.applied_to_evaluations is True


def test_merge_staging_file_routes_by_directory(temp_project):
    run_id = "route20260801T120000Z"
    create_run_manifest(run_id)
    candidate_path = (
        temp_project / "data" / "staging" / "runs" / run_id / "company_candidates" / "route-co.json"
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        json.dumps(
            {
                "company_name": "Route Test Co",
                "website": "https://route-test.example",
                "source_id": "test",
                "source_name": "Test",
                "source_url": "https://example.com/route",
                "confidence": 0.5,
            }
        ),
        encoding="utf-8",
    )
    result = merge_staging_file(candidate_path)
    assert result.success
    assert result.company_name == "Route Test Co"
