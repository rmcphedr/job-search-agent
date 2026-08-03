"""CLI for merging agent staging files into canonical data stores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.orchestration.handlers import merge_run_directory, merge_staging_file
from src.orchestration.manifest import create_run_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and merge agent staging JSON into canonical CSV stores.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Path to a single staging JSON file (object or array).",
    )
    parser.add_argument(
        "--run",
        type=str,
        help="Run ID — process all pending files under data/staging/runs/<run_id>/.",
    )
    parser.add_argument(
        "--init-run",
        type=str,
        metavar="RUN_ID",
        help="Create a new run manifest and directory structure.",
    )
    parser.add_argument(
        "--request",
        type=str,
        default="{}",
        help="JSON object for --init-run request metadata.",
    )
    parser.add_argument(
        "--force-re-eval",
        action="store_true",
        help="Merge evaluations even if company already has a canonical evaluation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.init_run:
        try:
            request = json.loads(args.request)
        except json.JSONDecodeError as exc:
            print(f"Invalid --request JSON: {exc}", file=sys.stderr)
            return 1
        manifest = create_run_manifest(args.init_run, request=request)
        print(json.dumps(manifest.to_dict(), indent=2))
        return 0

    if args.file:
        result = merge_staging_file(args.file, force_re_eval=args.force_re_eval)
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.success else 1

    if args.run:
        results = merge_run_directory(args.run, force_re_eval=args.force_re_eval)
        payload = [result.to_dict() for result in results]
        print(json.dumps(payload, indent=2))
        failed = sum(1 for result in results if not result.success)
        return 1 if failed else 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
