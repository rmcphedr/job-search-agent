"""Deterministic provenance policy for candidate application answers."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.database.db import get_project_root
from src.profile.master_profile import sync_status

PROFILE_FILES = frozenset({
    "user/master_cv.md", "user/career_profile.md", "user/proof_points.md",
    "user/project_inventory.md", "user/voice_style.md",
})
SENSITIVE = (
    "work_authorization", "authorized_to_work", "visa", "sponsorship",
    "salary", "compensation", "pay_expectation", "demographic", "race",
    "ethnicity", "gender", "disability", "veteran", "attestation",
    "certify", "legal", "consent", "privacy", "agree_to",
)
DIRECT_ACTION = ("consent", "privacy", "attestation", "certify", "agree_to")


def _fact(field_key: str, evidence: dict[str, Any]) -> str | None:
    facts = evidence.get("application_facts") or {}
    item = facts.get(field_key) if isinstance(facts, dict) else None
    if not isinstance(item, dict) or item.get("source") != "user_confirmed":
        return None
    value = item.get("value")
    return str(value).strip() if value is not None and str(value).strip() else None


def valid_profile_sources(evidence: dict[str, Any], project_root: Path | None = None) -> dict[str, str]:
    profiles = evidence.get("profile_files") or {}
    if not isinstance(profiles, dict):
        return {}
    accepted = {key: text for key, text in profiles.items()
                if key in PROFILE_FILES and isinstance(text, str)}
    if "user/master_cv.md" in accepted:
        try:
            current, _ = sync_status(project_root or get_project_root())
        except (OSError, RuntimeError, ValueError):
            current = False
        if not current:
            accepted.pop("user/master_cv.md")
    return accepted


def classify_answer(field: dict[str, Any], evidence: dict[str, Any]) -> str:
    """Return confirmed, approval_required, or human_required.

    A matching user-confirmed fact has priority. Candidate-owned profile text
    can support ordinary factual answers; generated documents are ignored.
    """
    key = str(field.get("field_key") or "").casefold().strip()
    label = str(field.get("label") or "").casefold()
    answer = str(field.get("answer") or "").strip()
    if not key or not answer:
        return "human_required"
    prompt = re.sub(r"[^a-z0-9]+", "_", key + " " + label)
    if any(token in prompt for token in DIRECT_ACTION):
        return "human_required"
    fact = _fact(key, evidence)
    if fact and fact.casefold() == answer.casefold():
        return "confirmed"
    if any(token in prompt for token in SENSITIVE):
        return "human_required"
    aliases = {key.replace("_", " "), key.replace("_", "-"), label.strip(" :?*")}
    aliases = {item for item in aliases if item}
    for content in valid_profile_sources(evidence).values():
        for line in content.splitlines():
            normalized = re.sub(r"[*#`-]", "", line).strip().casefold()
            for alias in aliases:
                if normalized.startswith(alias + ":") and answer.casefold() in normalized[len(alias) + 1:]:
                    return "confirmed"
    return "approval_required"
