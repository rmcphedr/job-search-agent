"""Apply calibration preference updates to profile with explicit confirmation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from src.database.db import get_project_root
from src.orchestration.calibration import calibration_path, load_calibration, save_calibration

logger = logging.getLogger(__name__)

AGENT_CALIBRATION_PATH = Path("user/agent_calibration.md")
PROFILE_PATH = Path("config/profile.yml")


@dataclass
class ProfileUpdateProposal:
    run_id: str
    preference_updates: list[str] = field(default_factory=list)
    markdown_entries: list[str] = field(default_factory=list)
    profile_changes: dict[str, object] = field(default_factory=dict)


def _utc_date() -> str:
    return datetime.now(UTC).date().isoformat()


def build_profile_update_proposal(run_id: str) -> ProfileUpdateProposal:
    calibration = load_calibration(run_id)
    if calibration is None:
        return ProfileUpdateProposal(run_id=run_id)

    markdown_entries = [
        f"### {_utc_date()} — calibration run `{run_id}`",
        *[f"- {item}" for item in calibration.preference_updates],
        "",
    ]
    return ProfileUpdateProposal(
        run_id=run_id,
        preference_updates=list(calibration.preference_updates),
        markdown_entries=markdown_entries,
        profile_changes={
            "note": "Preference themes captured for agent context; structured profile.yml fields unchanged unless explicitly mapped.",
            "preference_updates": calibration.preference_updates,
        },
    )


def append_agent_calibration_markdown(entries: list[str]) -> Path:
    path = get_project_root() / AGENT_CALIBRATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    block = "\n".join(entries).strip() + "\n"
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + "\n" + block, encoding="utf-8")
    return path


def apply_profile_updates(run_id: str, *, confirm: bool = False) -> dict[str, object]:
    """Persist preference themes to agent_calibration.md after explicit confirmation."""
    calibration = load_calibration(run_id)
    if calibration is None:
        return {"success": False, "error": f"No calibration file for run {run_id}"}

    if not calibration.preference_updates:
        return {"success": False, "error": "No preference_updates to apply"}

    proposal = build_profile_update_proposal(run_id)
    if not confirm:
        return {
            "success": False,
            "dry_run": True,
            "proposal": {
                "run_id": proposal.run_id,
                "preference_updates": proposal.preference_updates,
                "markdown_preview": "\n".join(proposal.markdown_entries),
            },
            "message": "Re-run with --confirm to append to user/agent_calibration.md",
        }

    markdown_path = append_agent_calibration_markdown(proposal.markdown_entries)
    calibration.applied_to_profile = True
    calibration.applied_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    save_calibration(run_id, calibration)

    return {
        "success": True,
        "run_id": run_id,
        "applied_to": str(markdown_path),
        "preference_updates": calibration.preference_updates,
    }


def load_profile_preferences() -> dict[str, object]:
    path = get_project_root() / PROFILE_PATH
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    preferences = data.get("preferences", {})
    return preferences if isinstance(preferences, dict) else {}


def export_proposal_json(run_id: str) -> str:
    proposal = build_profile_update_proposal(run_id)
    return json.dumps(
        {
            "run_id": proposal.run_id,
            "preference_updates": proposal.preference_updates,
            "markdown_preview": "\n".join(proposal.markdown_entries),
            "calibration_path": str(calibration_path(run_id)),
        },
        indent=2,
    )
