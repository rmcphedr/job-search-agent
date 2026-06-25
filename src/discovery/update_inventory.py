"""Update company inventory CSV with discovered company candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd
from rapidfuzz import fuzz

from src.database.db import get_project_root, load_settings
from src.discovery.link_utils import (
    clean_url,
    format_url_for_csv,
    get_domain,
    has_life_sciences_bc_member_url,
    is_external_url,
    is_life_sciences_bc_listing_url,
    is_life_sciences_bc_profile_url,
)
from src.discovery.models import CompanyCandidate

BASE_COLUMNS = [
    "company_id",
    "company_name",
    "website",
    "industry",
    "location",
    "size",
    "hiring_status",
    "priority",
    "last_checked",
]

DISCOVERY_COLUMNS = [
    "source_id",
    "source_url",
    "source_category",
    "confidence",
    "notes",
]

ALL_COLUMNS = BASE_COLUMNS + DISCOVERY_COLUMNS
NAME_SIMILARITY_THRESHOLD = 88

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class InventoryUpdateResult:
    existing_rows: int
    candidates_received: int
    inserted: int
    skipped_duplicates: int
    updated_fields: int


@dataclass
class InventoryCleanupResult:
    rows_before: int
    rows_removed: int
    rows_after: int
    removed_companies: list[str]


def get_inventory_path() -> Path:
    """Resolve the company inventory CSV path from settings."""
    try:
        settings = load_settings()
        paths = settings.get("paths", {})
        if isinstance(paths, dict):
            inventory_path = paths.get("company_inventory")
            if isinstance(inventory_path, str) and inventory_path.strip():
                return get_project_root() / inventory_path
    except RuntimeError:
        pass
    return get_project_root() / "data" / "company_inventory.csv"


def _normalize_website(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return clean_url(str(value))


def _format_url_columns_for_csv(frame: pd.DataFrame) -> pd.DataFrame:
    """Add a trailing space to URL columns so they stay visually separated in CSV."""
    formatted = frame.copy()
    for column in ("website", "source_url"):
        formatted[column] = formatted[column].apply(
            lambda value: format_url_for_csv(value) if not _is_empty(value) else ""
        )
    return formatted


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() == ""


def _load_inventory(inventory_path: Path) -> pd.DataFrame:
    if inventory_path.exists():
        frame = pd.read_csv(inventory_path, dtype=str)
    else:
        frame = pd.DataFrame(columns=ALL_COLUMNS)

    for column in ALL_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    return frame[ALL_COLUMNS].copy()


def _next_company_id(frame: pd.DataFrame) -> int:
    if frame.empty or frame["company_id"].eq("").all():
        return 1

    numeric_ids = pd.to_numeric(frame["company_id"], errors="coerce").dropna()
    if numeric_ids.empty:
        return 1
    return int(numeric_ids.max()) + 1


def _find_existing_index(frame: pd.DataFrame, candidate: CompanyCandidate) -> int | None:
    candidate_website = _normalize_website(candidate.website)
    candidate_source_url = _normalize_website(candidate.source_url)

    if candidate.source_id == "life_sciences_bc" and candidate_source_url:
        for index, row in frame.iterrows():
            row_website = _normalize_website(row.get("website"))
            row_source_url = _normalize_website(row.get("source_url"))
            if row_website == candidate_source_url or row_source_url == candidate_source_url:
                return int(index)

    if candidate_website:
        for index, row in frame.iterrows():
            row_website = _normalize_website(row.get("website"))
            if row_website and row_website == candidate_website:
                return int(index)

        candidate_domain = get_domain(candidate_website)
        source_domain = get_domain(candidate.source_url)
        if (
            candidate_domain
            and source_domain
            and is_external_url(candidate_website, source_domain)
        ):
            for index, row in frame.iterrows():
                row_website = _normalize_website(row.get("website"))
                row_domain = get_domain(row_website)
                if row_domain and row_domain == candidate_domain:
                    return int(index)

    best_index: int | None = None
    best_score = 0
    for index, row in frame.iterrows():
        existing_name = str(row.get("company_name", "")).strip()
        if not existing_name:
            continue
        score = fuzz.token_sort_ratio(
            candidate.company_name.lower(),
            existing_name.lower(),
        )
        if score >= NAME_SIMILARITY_THRESHOLD and score > best_score:
            best_score = score
            best_index = int(index)

    return best_index


def _is_valid_life_sciences_bc_row(row: pd.Series) -> bool:
    """Return True when a Life Sciences BC row references a member profile URL."""
    source_url = _normalize_website(row.get("source_url"))
    website = _normalize_website(row.get("website"))
    notes = str(row.get("notes", "") or "")

    if has_life_sciences_bc_member_url(source_url, website):
        return True

    profile_url = None
    if notes.startswith("{") and "profile_url" in notes:
        try:
            payload = json.loads(notes)
            if isinstance(payload, dict):
                profile_url = _normalize_website(payload.get("profile_url"))
        except json.JSONDecodeError:
            profile_url = None

    return has_life_sciences_bc_member_url(profile_url)


def _website_quality(website: str | None, source_id: str) -> int:
    """Return a higher score for more useful company website values."""
    normalized = _normalize_website(website)
    if not normalized:
        return 0

    if source_id == "life_sciences_bc":
        if is_external_url(normalized, "lifesciencesbc.ca"):
            return 3
        if is_life_sciences_bc_profile_url(normalized):
            return 1

    domain = get_domain(normalized)
    if domain and "lifesciencesbc.ca" not in domain:
        return 3
    return 2


def _source_url_quality(source_url: str | None, source_id: str) -> int:
    normalized = _normalize_website(source_url)
    if not normalized:
        return 0

    if source_id == "life_sciences_bc":
        if is_life_sciences_bc_profile_url(normalized):
            return 3
        if is_life_sciences_bc_listing_url(normalized):
            return 1

    return 2


def _notes_quality(notes: str | None) -> int:
    if _is_empty(notes):
        return 0
    text = str(notes)
    if "life_sciences_bc_profile" in text:
        return 3
    if text.startswith("{") and "profile_url" in text:
        return 3
    return 1


def _confidence_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _should_upgrade_website(existing: object, new_value: str, candidate: CompanyCandidate) -> bool:
    existing_quality = _website_quality(str(existing) if not _is_empty(existing) else None, candidate.source_id)
    new_quality = _website_quality(new_value, candidate.source_id)
    return new_quality > existing_quality


def _should_upgrade_source_url(existing: object, new_value: str, candidate: CompanyCandidate) -> bool:
    existing_quality = _source_url_quality(str(existing) if not _is_empty(existing) else None, candidate.source_id)
    new_quality = _source_url_quality(new_value, candidate.source_id)
    return new_quality > existing_quality


def _should_upgrade_notes(existing: object, new_value: str) -> bool:
    return _notes_quality(new_value) > _notes_quality(str(existing) if not _is_empty(existing) else None)


def _should_upgrade_confidence(existing: object, new_value: str) -> bool:
    return _confidence_value(new_value) > _confidence_value(existing)


def _should_upgrade_category(existing: object, new_value: str) -> bool:
    if _is_empty(new_value):
        return False
    if _is_empty(existing):
        return True
    existing_text = str(existing).strip()
    new_text = str(new_value).strip()
    if existing_text == new_text:
        return False
    generic_values = {"Life Sciences BC Member", ""}
    return existing_text in generic_values and new_text not in generic_values


def _merge_field(
    row: pd.Series,
    field: str,
    new_value: str,
    should_upgrade,
) -> int:
    if _is_empty(new_value):
        return 0

    existing = row.get(field)
    if _is_empty(existing):
        row[field] = new_value
        return 1
    if should_upgrade(existing, new_value):
        row[field] = new_value
        return 1
    return 0


def _candidate_to_row(candidate: CompanyCandidate, company_id: int) -> dict[str, object]:
    return {
        "company_id": str(company_id),
        "company_name": candidate.company_name,
        "website": format_url_for_csv(candidate.website),
        "industry": candidate.source_category or "",
        "location": "",
        "size": "",
        "hiring_status": "Unknown",
        "priority": "Medium" if candidate.confidence >= 0.6 else "Low",
        "last_checked": "",
        "source_id": candidate.source_id,
        "source_url": format_url_for_csv(candidate.source_url),
        "source_category": candidate.source_category or "",
        "confidence": f"{candidate.confidence:.2f}",
        "notes": candidate.notes or "",
    }


def _fill_empty_fields(row: pd.Series, candidate: CompanyCandidate) -> tuple[pd.Series, int]:
    updates = 0
    candidate_row = _candidate_to_row(candidate, company_id=int(row["company_id"] or 0))

    merge_specs = [
        (
            "website",
            format_url_for_csv(candidate.website),
            lambda existing, new_value: _should_upgrade_website(existing, new_value, candidate),
        ),
        (
            "source_url",
            format_url_for_csv(candidate.source_url),
            lambda existing, new_value: _should_upgrade_source_url(existing, new_value, candidate),
        ),
        (
            "notes",
            candidate.notes or "",
            lambda existing, new_value: _should_upgrade_notes(existing, new_value),
        ),
        (
            "confidence",
            f"{candidate.confidence:.2f}",
            lambda existing, new_value: _should_upgrade_confidence(existing, new_value),
        ),
        (
            "industry",
            candidate.source_category or "",
            lambda existing, new_value: _should_upgrade_category(existing, new_value),
        ),
        (
            "source_category",
            candidate.source_category or "",
            lambda existing, new_value: _should_upgrade_category(existing, new_value),
        ),
    ]

    for field, new_value, should_upgrade in merge_specs:
        updates += _merge_field(row, field, new_value, should_upgrade)

    for field, new_value in (
        ("source_id", candidate.source_id),
    ):
        if not _is_empty(new_value) and _is_empty(row.get(field)):
            row[field] = new_value
            updates += 1

    if _is_empty(row.get("hiring_status")):
        row["hiring_status"] = candidate_row["hiring_status"]
        updates += 1

    if _is_empty(row.get("priority")):
        row["priority"] = candidate_row["priority"]
        updates += 1

    return row, updates


def load_known_lsbc_profile_urls(inventory_path: Path | None = None) -> set[str]:
    """Return normalized Life Sciences BC member profile URLs already in inventory."""
    path = inventory_path or get_inventory_path()
    if not path.exists():
        return set()

    frame = pd.read_csv(path, dtype=str)
    known: set[str] = set()

    for _, row in frame.iterrows():
        for field in ("source_url", "website"):
            url = _normalize_website(row.get(field))
            if url and is_life_sciences_bc_profile_url(url):
                known.add(url.rstrip("/"))

        notes = str(row.get("notes", "") or "")
        if notes.startswith("{") and "profile_url" in notes:
            try:
                payload = json.loads(notes)
                if isinstance(payload, dict):
                    profile_url = _normalize_website(payload.get("profile_url"))
                    if profile_url and is_life_sciences_bc_profile_url(profile_url):
                        known.add(profile_url.rstrip("/"))
            except json.JSONDecodeError:
                pass

    return known


def update_inventory(
    candidates: list[CompanyCandidate],
    inventory_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> InventoryUpdateResult:
    """Merge discovered candidates into the company inventory CSV."""
    path = inventory_path or get_inventory_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    frame = _load_inventory(path)
    existing_rows = len(frame)

    inserted = 0
    skipped_duplicates = 0
    updated_fields = 0
    next_id = _next_company_id(frame)
    total = len(candidates)

    for index, candidate in enumerate(candidates, start=1):
        if progress_callback is not None:
            progress_callback(index, total, f"Merging: {candidate.company_name}")

        if not candidate.website or not str(candidate.website).strip():
            skipped_duplicates += 1
            continue

        if candidate.source_id == "life_sciences_bc" and not has_life_sciences_bc_member_url(
            candidate.source_url,
            candidate.website,
        ):
            skipped_duplicates += 1
            continue

        match_index = _find_existing_index(frame, candidate)
        if match_index is not None:
            updated_row, field_updates = _fill_empty_fields(frame.loc[match_index], candidate)
            frame.loc[match_index] = updated_row
            if field_updates:
                updated_fields += field_updates
            else:
                skipped_duplicates += 1
            continue

        new_row = _candidate_to_row(candidate, company_id=next_id)
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)
        next_id += 1
        inserted += 1

    frame = _format_url_columns_for_csv(frame)
    frame.to_csv(path, index=False)

    return InventoryUpdateResult(
        existing_rows=existing_rows,
        candidates_received=len(candidates),
        inserted=inserted,
        skipped_duplicates=skipped_duplicates,
        updated_fields=updated_fields,
    )


def reformat_inventory_urls(inventory_path: Path | None = None) -> int:
    """Rewrite website and source_url columns with trailing-space CSV formatting."""
    path = inventory_path or get_inventory_path()
    frame = _load_inventory(path)
    frame = _format_url_columns_for_csv(frame)
    frame.to_csv(path, index=False)
    return len(frame)


def clean_life_sciences_bc_inventory(inventory_path: Path | None = None) -> InventoryCleanupResult:
    """Remove Life Sciences BC rows that do not reference a member profile URL."""
    path = inventory_path or get_inventory_path()
    frame = pd.read_csv(path, dtype=str)
    rows_before = len(frame)

    if frame.empty:
        return InventoryCleanupResult(rows_before, 0, 0, [])

    for column in ALL_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    lsbc_mask = frame["source_id"].fillna("").str.lower() == "life_sciences_bc"
    invalid_lsbc = lsbc_mask & ~frame.apply(_is_valid_life_sciences_bc_row, axis=1)
    removed_companies = frame.loc[invalid_lsbc, "company_name"].fillna("").astype(str).tolist()

    cleaned = frame.loc[~invalid_lsbc].copy()
    cleaned = _format_url_columns_for_csv(cleaned)
    cleaned.to_csv(path, index=False)

    return InventoryCleanupResult(
        rows_before=rows_before,
        rows_removed=int(invalid_lsbc.sum()),
        rows_after=len(cleaned),
        removed_companies=removed_companies,
    )
