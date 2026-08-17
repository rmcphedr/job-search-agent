"""Test a single directory source and preview extracted candidates."""

from __future__ import annotations

import argparse
import logging

from src.discovery.deduplicate import deduplicate_candidates
from src.discovery.load_sources import load_directory_sources
from src.discovery.models import CompanyCandidate
from src.discovery.strategies import extract_candidates
from src.discovery.update_inventory import update_inventory

NOTES_PREVIEW_LEN = 120


def _notes_preview(notes: str | None) -> str:
    if not notes:
        return ""
    compact = " ".join(notes.split())
    if len(compact) <= NOTES_PREVIEW_LEN:
        return compact
    return f"{compact[:NOTES_PREVIEW_LEN]}..."


def _print_candidate(index: int, candidate: CompanyCandidate) -> None:
    print(f"[{index}] {candidate.company_name}")
    print(f"    website:         {candidate.website}")
    print(f"    confidence:      {candidate.confidence:.2f}")
    print(f"    source_category: {candidate.source_category}")
    print(f"    source_url:      {candidate.source_url}")
    print(f"    notes preview:   {_notes_preview(candidate.notes)}")


def run_source_test(source_id: str, limit: int | None = None, write: bool = False) -> None:
    sources = load_directory_sources(source_id=source_id)
    source = sources[0]

    profile_limit = limit
    if source.source_id == "life_sciences_bc" and profile_limit is not None:
        print(f"Following up to {profile_limit} Life Sciences BC profile link(s)...")

    candidates = extract_candidates(source, profile_limit=profile_limit)
    deduped = deduplicate_candidates(candidates)

    if limit is not None and source.source_id != "life_sciences_bc":
        deduped = deduped[:limit]

    print(f"Source: {source.source_id} ({source.name})")
    print(f"Extracted candidates: {len(candidates)}")
    print(f"Deduplicated candidates: {len(deduped)}")
    print("Preview:")
    for index, candidate in enumerate(deduped, start=1):
        _print_candidate(index, candidate)

    if write:
        result = update_inventory(deduped)
        print("Inventory update:")
        print(f"  existing rows: {result.existing_rows}")
        print(f"  candidates received: {result.candidates_received}")
        print(f"  inserted: {result.inserted}")
        print(f"  skipped as duplicates: {result.skipped_duplicates}")
        print(f"  updated fields: {result.updated_fields}")
    else:
        print("Dry preview only: company inventory was not updated.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test one directory source and preview extracted company candidates."
    )
    parser.add_argument(
        "--source",
        dest="source_id",
        required=True,
        help="Directory source_id to test.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="For life_sciences_bc, limits profile pages followed. Otherwise limits preview rows.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write deduplicated candidates to data/company_inventory.csv.",
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
        run_source_test(args.source_id, limit=args.limit, write=args.write)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Test failed: {exc}") from exc


if __name__ == "__main__":
    main()
