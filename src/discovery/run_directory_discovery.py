"""CLI runner for directory source discovery."""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.database.db import get_project_root
from src.discovery.deduplicate import deduplicate_candidates
from src.discovery.load_sources import load_directory_sources
from src.discovery.models import CompanyCandidate
from src.discovery.strategies import extract_candidates
from src.discovery.update_inventory import update_inventory

DEFAULT_OUTPUT = get_project_root() / "outputs" / "directory_candidates.csv"


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _save_candidates_csv(candidates: list[CompanyCandidate], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [candidate.model_dump() for candidate in candidates]
    frame = pd.DataFrame(rows)
    frame.to_csv(output_path, index=False)


def run_discovery(
    *,
    source_id: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    output_candidates: Path = DEFAULT_OUTPUT,
) -> None:
    sources = load_directory_sources(source_id=source_id)

    all_candidates: list[CompanyCandidate] = []
    per_source_counts: dict[str, int] = defaultdict(int)

    for source in sources:
        profile_limit = limit if source.source_id == "life_sciences_bc" else None
        candidates = extract_candidates(source, profile_limit=profile_limit)
        per_source_counts[source.source_id] = len(candidates)
        all_candidates.extend(candidates)

    deduped = deduplicate_candidates(all_candidates)
    lsbc_only = len(sources) == 1 and sources[0].source_id == "life_sciences_bc"
    if limit is not None and not lsbc_only:
        deduped = deduped[:limit]

    _save_candidates_csv(deduped, output_candidates)

    print(f"Loaded {len(sources)} source(s)")
    print("Candidates by source:")
    for source in sources:
        print(f"  {source.source_id}: {per_source_counts[source.source_id]}")
    print(f"Deduplicated candidates: {len(deduped)}")
    print(f"Saved candidates to {output_candidates}")

    if dry_run:
        print("Dry run enabled: company inventory was not updated.")
        return

    result = update_inventory(deduped)
    print("Inventory update:")
    print(f"  existing rows: {result.existing_rows}")
    print(f"  candidates received: {result.candidates_received}")
    print(f"  inserted: {result.inserted}")
    print(f"  skipped as duplicates: {result.skipped_duplicates}")
    print(f"  updated fields: {result.updated_fields}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover companies from curated directory pages and update inventory."
    )
    parser.add_argument(
        "--source",
        dest="source_id",
        help="Run only the specified source_id.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and save candidates without updating company_inventory.csv.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit profile pages for life_sciences_bc, or deduplicated candidates for other sources.",
    )
    parser.add_argument(
        "--output-candidates",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path for the extracted candidates CSV.",
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
    _configure_logging(args.verbose)

    try:
        run_discovery(
            source_id=args.source_id,
            dry_run=args.dry_run,
            limit=args.limit,
            output_candidates=args.output_candidates,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Directory discovery failed: {exc}") from exc


if __name__ == "__main__":
    main()
