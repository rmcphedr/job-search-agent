"""File-based cache for LLM fit scoring results."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.database.db import get_project_root, load_settings
from src.llm.llm_client import load_llm_config
from src.profile.master_profile import master_profile_hash


def get_cache_dir() -> Path:
    """Resolve the cache directory from project settings."""
    try:
        settings = load_settings()
        paths = settings.get("paths", {})
        if isinstance(paths, dict):
            cache_path = paths.get("cache")
            if isinstance(cache_path, str) and cache_path.strip():
                return get_project_root() / cache_path
    except RuntimeError:
        pass
    return get_project_root() / "data" / "cache"


def is_cache_enabled(config: dict[str, Any] | None = None) -> bool:
    cfg = config or load_llm_config()
    return bool(cfg.get("cache_enabled", True))


def company_cache_key(company_record: dict[str, object]) -> str:
    """Return SHA256 cache key for a company record."""
    notes = company_record.get("notes", "")
    description = str(notes)
    if isinstance(notes, str) and notes.strip().startswith("{"):
        try:
            payload = json.loads(notes)
            if isinstance(payload, dict) and payload.get("description"):
                description = str(payload.get("description"))
        except json.JSONDecodeError:
            pass

    payload = "".join(
        [
            _normalize(company_record.get("company_name")),
            _normalize(company_record.get("industry")),
            description,
            master_profile_hash(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def job_cache_key(job_record: dict[str, object]) -> str:
    """Return SHA256 cache key for a job record."""
    payload = "".join(
        [
            _normalize(job_record.get("title") or job_record.get("job_title")),
            _normalize(job_record.get("company") or job_record.get("company_name")),
            _normalize(job_record.get("description")),
            master_profile_hash(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def job_triage_cache_key(job_record: dict[str, object]) -> str:
    """Return SHA256 cache key for title-only job triage."""
    matched = job_record.get("matched_keywords") or []
    if isinstance(matched, list):
        matched_text = ",".join(str(item) for item in matched)
    else:
        matched_text = str(matched)
    payload = "".join(
        [
            _normalize(job_record.get("title") or job_record.get("job_title")),
            _normalize(job_record.get("company") or job_record.get("company_name")),
            _normalize(job_record.get("location")),
            matched_text,
            _normalize(job_record.get("keyword_score")),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_cached_result(cache_type: str, cache_key: str) -> dict[str, Any] | None:
    """Load a cached JSON result if present."""
    path = get_cache_dir() / cache_type / f"{cache_key}.json"
    if not path.exists():
        return None

    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None

    if isinstance(data, dict):
        return data
    return None


def save_cached_result(cache_type: str, cache_key: str, result: dict[str, Any]) -> Path:
    """Persist a scoring result to the cache."""
    cache_dir = get_cache_dir() / cache_type
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{cache_key}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    return path


def _normalize(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
