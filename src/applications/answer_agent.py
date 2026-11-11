"""Bounded Hermes bridge for staged application answer drafts."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.applications.answer_models import AnswerDraft
from src.applications.answer_policy import classify_answer, valid_profile_sources
from src.database.db import get_project_root


def answer_path(run_id: int, field_key: str, root: Path | None = None) -> Path:
    if run_id <= 0 or not re.fullmatch(r"[A-Za-z0-9_:-]+", field_key):
        raise ValueError("Invalid run ID or field key")
    return (root or get_project_root()) / "data" / "staging" / "application_runs" / str(run_id) / f"answer_{field_key}.json"


def draft_answer(run_id: int, question: dict, evidence: dict) -> AnswerDraft:
    """Ask Hermes for one draft; validate and retain it only in staging."""
    key = str(question.get("field_key") or "")
    root = get_project_root()
    output = answer_path(run_id, key, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    profiles = valid_profile_sources(evidence, root)
    safe_evidence: dict[str, Any] = {
        "profile_files": profiles,
        "application_facts": evidence.get("application_facts") or {},
        "job_evidence": evidence.get("job_evidence") or {},
    }
    request = output.with_name(f"request_{key}.json")
    request.write_text(json.dumps({"question": question, "evidence": safe_evidence}, indent=2) + "\n", encoding="utf-8")
    skill = root / "skills" / "application_answering" / "SKILL.md"
    prompt = (
        f"Follow {skill}. Read the request at {request}. Write exactly one AnswerDraft JSON object.\n"
        f"OUTPUT_PATH: {output}\n"
    )
    executable = os.environ.get("HERMES_EXECUTABLE", "hermes")
    timeout = int(os.environ.get("APPLICATION_ANSWER_TIMEOUT_SECONDS", "120"))
    if timeout < 1 or timeout > 600:
        raise ValueError("Answer timeout must be between 1 and 600 seconds")
    completed = subprocess.run([executable, "--oneshot", prompt], cwd=root, capture_output=True,
                               text=True, timeout=timeout, check=False)
    if completed.returncode != 0 or not output.is_file():
        raise RuntimeError(f"Hermes answer drafting failed (exit {completed.returncode})")
    try:
        draft = AnswerDraft.model_validate_json(output.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        raise ValueError("Invalid staged answer JSON") from exc
    if draft.field_key != key:
        raise ValueError("Staged answer field key does not match request")
    valid_refs = set(profiles) | {f"application_facts:{name}" for name in safe_evidence["application_facts"]}
    if any(ref not in valid_refs for ref in draft.evidence_refs):
        raise ValueError("Staged answer cites an unavailable evidence source")
    policy = classify_answer({**question, "answer": draft.answer}, safe_evidence)
    draft.approval_status = policy
    output.write_text(draft.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return draft
