"""Import company inventory rows from CSV into the companies table."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

from src.database.db import get_connection, get_project_root, load_settings
from src.discovery.link_utils import clean_url


OPTIONAL_COLUMNS = (
    "company_id",
    "industry",
    "location",
    "size",
    "hiring_status",
    "priority",
    "last_checked",
)


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _parse_company_id(value: Any) -> int | None:
    cleaned = _clean_value(value)
    if cleaned is None:
        return None
    try:
        return int(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid company_id value: {value!r}") from exc


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


def _clean_website(value: Any) -> str | None:
    return clean_url(_clean_value(value))


def _normalize_row(row: dict[str, Any]) -> dict[str, str | int | None]:
    company_name = _clean_value(row.get("company_name"))
    website = _clean_website(row.get("website"))

    if not company_name:
        raise ValueError("Each row must include a non-empty company_name.")
    if not website:
        raise ValueError("Each row must include a non-empty website.")

    normalized: dict[str, str | int | None] = {
        "company_id": _parse_company_id(row.get("company_id")),
        "company_name": company_name,
        "website": website,
    }

    for column in OPTIONAL_COLUMNS:
        if column == "company_id":
            continue
        normalized[column] = _clean_value(row.get(column))

    return normalized


def import_inventory(csv_path: Path | None = None) -> tuple[int, int]:
    """Import companies from CSV. Returns (inserted_count, updated_count)."""
    inventory_path = csv_path or get_inventory_path()
    if not inventory_path.exists():
        raise FileNotFoundError(f"Company inventory CSV not found: {inventory_path}")

    inserted = 0
    updated = 0

    with get_connection() as connection:
        with inventory_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError(f"CSV file is missing a header row: {inventory_path}")

            for row_number, row in enumerate(reader, start=2):
                try:
                    normalized = _normalize_row(row)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid row {row_number} in {inventory_path}: {exc}"
                    ) from exc

                existing = connection.execute(
                    "SELECT company_id FROM companies WHERE website = ?;",
                    (normalized["website"],),
                ).fetchone()

                if existing is not None:
                    connection.execute(
                        """
                        UPDATE companies
                        SET company_name = ?,
                            industry = ?,
                            location = ?,
                            size = ?,
                            hiring_status = ?,
                            priority = ?,
                            last_checked = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE website = ?;
                        """,
                        (
                            normalized["company_name"],
                            normalized["industry"],
                            normalized["location"],
                            normalized["size"],
                            normalized["hiring_status"],
                            normalized["priority"],
                            normalized["last_checked"],
                            normalized["website"],
                        ),
                    )
                    updated += 1
                    continue

                if normalized["company_id"] is not None:
                    connection.execute(
                        """
                        INSERT INTO companies (
                            company_id,
                            company_name,
                            website,
                            industry,
                            location,
                            size,
                            hiring_status,
                            priority,
                            last_checked
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            normalized["company_id"],
                            normalized["company_name"],
                            normalized["website"],
                            normalized["industry"],
                            normalized["location"],
                            normalized["size"],
                            normalized["hiring_status"],
                            normalized["priority"],
                            normalized["last_checked"],
                        ),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO companies (
                            company_name,
                            website,
                            industry,
                            location,
                            size,
                            hiring_status,
                            priority,
                            last_checked
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            normalized["company_name"],
                            normalized["website"],
                            normalized["industry"],
                            normalized["location"],
                            normalized["size"],
                            normalized["hiring_status"],
                            normalized["priority"],
                            normalized["last_checked"],
                        ),
                    )
                inserted += 1

        connection.commit()

    return inserted, updated


def main() -> None:
    try:
        inserted, updated = import_inventory()
    except (FileNotFoundError, ValueError, sqlite3.Error, RuntimeError) as exc:
        raise SystemExit(f"Import failed: {exc}") from exc

    print(f"Import complete: {inserted} inserted, {updated} updated.")


if __name__ == "__main__":
    main()
