"""Keyword filtering for extracted job candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.database.db import get_project_root
from src.jobs.job_models import JobCandidate
from src.jobs.job_url_utils import normalize_text

DEFAULT_MIN_KEYWORD_SCORE = 0.2
KEYWORD_CONFIG_PATH = get_project_root() / "config" / "job_keywords.yaml"


def load_job_keywords(config_path: Path | None = None) -> dict[str, list[str]]:
    path = config_path or KEYWORD_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Job keyword config not found: {path}")

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise RuntimeError(f"Job keyword config must be a mapping: {path}")

    groups = ("high_value_roles", "domain_keywords", "technical_keywords", "exclude_role_keywords")
    keywords: dict[str, list[str]] = {}
    for group in groups:
        values = data.get(group, [])
        if not isinstance(values, list):
            raise RuntimeError(f"Keyword group {group!r} must be a list in {path}")
        keywords[group] = [str(value).strip().lower() for value in values if str(value).strip()]
    return keywords


def _search_text(candidate: JobCandidate, *, title_only: bool = False) -> str:
    if title_only:
        return normalize_text(
            " ".join(part for part in (candidate.title, candidate.location or "") if part)
        )
    return normalize_text(
        " ".join(
            part
            for part in (
                candidate.title,
                candidate.location or "",
                candidate.description or "",
            )
            if part
        )
    )


def _find_matches(text: str, keywords: list[str]) -> list[str]:
    matches: list[str] = []
    for keyword in keywords:
        if keyword and keyword in text:
            matches.append(keyword)
    return matches


def score_job(
    candidate: JobCandidate,
    keywords: dict[str, list[str]] | None = None,
    *,
    title_only: bool = False,
) -> tuple[float, list[str]]:
    """Return keyword_score and matched keyword list for a job candidate."""
    config = keywords or load_job_keywords()
    text = _search_text(candidate, title_only=title_only)
    title_text = normalize_text(candidate.title)

    high_value_matches = _find_matches(title_text, config["high_value_roles"])
    if not high_value_matches:
        high_value_matches = _find_matches(text, config["high_value_roles"])

    domain_matches = _find_matches(text, config["domain_keywords"])
    technical_matches = _find_matches(text, config["technical_keywords"])
    exclude_matches = _find_matches(title_text, config["exclude_role_keywords"])

    matched = sorted(set(high_value_matches + domain_matches + technical_matches))
    score = 0.0
    if high_value_matches:
        score += 0.55
    if domain_matches:
        score += 0.25
    if technical_matches:
        score += 0.20
    if title_text and any(keyword in title_text for keyword in matched):
        score += 0.10
    if exclude_matches and not (high_value_matches or domain_matches or technical_matches):
        score = min(score, 0.10)

    return min(score, 1.0), matched


def should_save_job(
    candidate: JobCandidate,
    *,
    min_keyword_score: float = DEFAULT_MIN_KEYWORD_SCORE,
    keywords: dict[str, list[str]] | None = None,
    title_only: bool = False,
) -> bool:
    """Return True if the job should be saved based on keyword filtering."""
    config = keywords or load_job_keywords()
    score, matched = score_job(candidate, config, title_only=title_only)
    candidate.keyword_score = score
    candidate.matched_keywords = matched

    title_text = normalize_text(candidate.title)
    if any(keyword in title_text for keyword in config["high_value_roles"]):
        return True
    return score >= min_keyword_score


def prescreen_jobs(
    candidates: list[JobCandidate],
    *,
    min_keyword_score: float = DEFAULT_MIN_KEYWORD_SCORE,
    title_only: bool = True,
) -> list[JobCandidate]:
    """Cheap title/metadata pre-screen before fetching full job descriptions."""
    keywords = load_job_keywords()
    screened: list[JobCandidate] = []
    for candidate in candidates:
        score, matched = score_job(candidate, keywords, title_only=title_only)
        updated = candidate.model_copy(
            update={"keyword_score": score, "matched_keywords": matched}
        )
        if should_save_job(
            updated,
            min_keyword_score=min_keyword_score,
            keywords=keywords,
            title_only=title_only,
        ):
            screened.append(updated)
    screened.sort(key=lambda job: job.keyword_score, reverse=True)
    return screened


def filter_jobs(
    candidates: list[JobCandidate],
    *,
    min_keyword_score: float = DEFAULT_MIN_KEYWORD_SCORE,
    title_only: bool = False,
) -> list[JobCandidate]:
    """Filter and score job candidates by keyword relevance."""
    keywords = load_job_keywords()
    filtered: list[JobCandidate] = []
    for candidate in candidates:
        score, matched = score_job(candidate, keywords, title_only=title_only)
        updated = candidate.model_copy(
            update={"keyword_score": score, "matched_keywords": matched}
        )
        if should_save_job(
            updated,
            min_keyword_score=min_keyword_score,
            keywords=keywords,
            title_only=title_only,
        ):
            filtered.append(updated)
    return filtered
