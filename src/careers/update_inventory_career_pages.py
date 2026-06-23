"""Update company inventory CSV with discovered career page URLs."""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd

from src.database.db import get_project_root, load_settings
from src.discovery.link_utils import clean_url, format_url_for_csv
from src.careers.find_career_page import find_career_page

logger = logging.getLogger(__name__)

CAREER_COLUMNS = (
    "career_page",
    "career_page_status",
    "career_page_confidence",
    "career_page_checked_at",
    "career_page_notes",
)

DEFAULT_OUTPUT = get_project_root() / "outputs" / "career_page_results.csv"


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


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() == ""


def _has_existing_career_page(value: object) -> bool:
    return not _is_empty(value)


def _ensure_career_columns(frame: pd.DataFrame) -> pd.DataFrame:
    updated = frame.copy()
    for column in CAREER_COLUMNS:
        if column not in updated.columns:
            updated[column] = ""
    return updated


def _format_career_page_value(value: str) -> str:
    if value == "NOT FOUND" or _is_empty(value):
        return "NOT FOUND"
    return format_url_for_csv(value)


def _load_inventory(inventory_path: Path) -> pd.DataFrame:
    if not inventory_path.exists():
        raise FileNotFoundError(f"Company inventory CSV not found: {inventory_path}")
    frame = pd.read_csv(inventory_path, dtype=str)
    return _ensure_career_columns(frame)


def _company_matches(row: pd.Series, company_filter: str) -> bool:
    name = str(row.get("company_name", "")).strip().lower()
    target = company_filter.strip().lower()
    return name == target or target in name


def run_update(
    *,
    limit: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    company: str | None = None,
    sleep_seconds: float = 0.0,
    output_path: Path = DEFAULT_OUTPUT,
    inventory_path: Path | None = None,
) -> pd.DataFrame:
    path = inventory_path or get_inventory_path()
    frame = pd.read_csv(path, dtype=str)
    original_columns = list(frame.columns)
    frame = _ensure_career_columns(frame)

    results: list[dict[str, object]] = []
    processed = 0

    for index, row in frame.iterrows():
        if company and not _company_matches(row, company):
            continue

        existing_career_page = row.get("career_page")
        if _has_existing_career_page(existing_career_page) and not force:
            continue

        homepage = clean_url(str(row.get("website", "")))
        company_name = str(row.get("company_name", "")).strip()

        if not homepage:
            result = {
                "company_id": row.get("company_id", ""),
                "company_name": company_name,
                "website": row.get("website", ""),
                "career_page": "NOT FOUND",
                "career_page_status": "ERROR",
                "career_page_confidence": "0.00",
                "career_page_checked_at": "",
                "career_page_notes": "Missing or invalid website URL",
            }
        else:
            logger.info("Finding career page for %s (%s)", company_name, homepage)
            discovery = find_career_page(homepage)
            result = {
                "company_id": row.get("company_id", ""),
                "company_name": company_name,
                "website": row.get("website", ""),
                "career_page": _format_career_page_value(discovery["career_page"]),
                "career_page_status": discovery["status"],
                "career_page_confidence": f"{discovery['confidence']:.2f}",
                "career_page_checked_at": discovery["checked_at"],
                "career_page_notes": discovery["notes"],
            }

            if not dry_run:
                frame.at[index, "career_page"] = result["career_page"]
                frame.at[index, "career_page_status"] = result["career_page_status"]
                frame.at[index, "career_page_confidence"] = result["career_page_confidence"]
                frame.at[index, "career_page_checked_at"] = result["career_page_checked_at"]
                frame.at[index, "career_page_notes"] = result["career_page_notes"]

        results.append(result)
        processed += 1

        if limit is not None and processed >= limit:
            break

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    results_frame = pd.DataFrame(results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results_frame.to_csv(output_path, index=False)

    if not dry_run and results:
        ordered_columns = original_columns + [
            column for column in CAREER_COLUMNS if column not in original_columns
        ]
        frame = frame[ordered_columns]
        frame.to_csv(path, index=False)

    return results_frame


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find company career pages and update company_inventory.csv."
    )
    parser.add_argument("--limit", type=int, default=None, help="Process at most N companies.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing career_page values.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover career pages without updating company_inventory.csv.",
    )
    parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Process one company by exact or partial name match.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep between company requests.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path for the career page results preview CSV.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable informational logging.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    try:
        results = run_update(
            limit=args.limit,
            force=args.force,
            dry_run=args.dry_run,
            company=args.company,
            sleep_seconds=args.sleep,
            output_path=args.output,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Career page update failed: {exc}") from exc

    print(f"Processed companies: {len(results)}")
    print(f"Saved results preview to {args.output}")
    if args.dry_run:
        print("Dry run enabled: company inventory was not updated.")
    else:
        print(f"Updated inventory at {get_inventory_path()}")

    if not results.empty:
        print("\nPreview:")
        for _, row in results.iterrows():
            print(
                f"- {row['company_name']}: {row['career_page']} "
                f"(status={row['career_page_status']}, confidence={row['career_page_confidence']})"
            )


if __name__ == "__main__":
    main()
