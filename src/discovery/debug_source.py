"""Debug helper for inspecting directory source listing pages."""

from __future__ import annotations

import argparse
import logging

from src.discovery.fetch import fetch_url
from src.discovery.load_sources import load_directory_sources
from src.discovery.strategies import collect_life_sciences_bc_profile_urls

logger = logging.getLogger(__name__)


def debug_source(source_id: str, max_links: int = 50) -> None:
    sources = load_directory_sources(source_id=source_id)
    source = sources[0]

    print(f"Source: {source.source_id} ({source.name})")
    print(f"Listing URL: {source.url}")
    print(f"Strategy: {source.strategy}")

    status_code, html = fetch_url(source.url)
    print(f"Fetch status: {status_code}")
    if status_code != 200 or not html.strip():
        raise RuntimeError(f"Failed to fetch listing page for {source.source_id}")

    if source.source_id != "life_sciences_bc":
        print("Detailed link debugging is currently optimized for life_sciences_bc.")
        return

    profile_links = collect_life_sciences_bc_profile_urls(source, html, max_links=max_links)
    print(f"Profile links found (showing up to {max_links}): {len(profile_links)}")
    for index, (profile_url, listing_name) in enumerate(profile_links, start=1):
        label = listing_name or "(no listing anchor text)"
        print(f"  {index:>3}. {label} -> {profile_url}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect directory listing pages and profile link discovery."
    )
    parser.add_argument(
        "--source",
        dest="source_id",
        required=True,
        help="Directory source_id to debug.",
    )
    parser.add_argument(
        "--max-links",
        type=int,
        default=50,
        help="Maximum number of profile links to display.",
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
        debug_source(args.source_id, max_links=args.max_links)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Debug failed: {exc}") from exc


if __name__ == "__main__":
    main()
