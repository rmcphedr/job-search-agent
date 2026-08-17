"""CLI for calibration capture and application."""

from __future__ import annotations

import argparse
import json
import sys

from src.orchestration.apply_preferences import apply_profile_updates, export_proposal_json
from src.orchestration.calibration import apply_calibration_to_evaluations, append_calibration_entry
from src.orchestration.calibration_models import CalibrationCorrection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage run calibration feedback.")
    parser.add_argument("--run", required=True, help="Run ID under data/staging/runs/")

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_correction = subparsers.add_parser("add-correction", help="Append a score correction.")
    add_correction.add_argument("--company", required=True)
    add_correction.add_argument("--corrected-score", type=float, required=True)
    add_correction.add_argument("--original-score", type=float, default=None)
    add_correction.add_argument("--feedback", default="")
    add_correction.add_argument("--preference", action="append", default=[], help="Preference theme to store.")

    subparsers.add_parser("apply-evaluations", help="Apply corrections to data/company_evaluations.csv")
    subparsers.add_parser("propose-profile", help="Preview profile/calibration markdown updates (dry run).")

    apply_profile = subparsers.add_parser("apply-profile", help="Append preference themes to user/agent_calibration.md")
    apply_profile.add_argument(
        "--confirm",
        action="store_true",
        help="Required to write user/agent_calibration.md",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "add-correction":
        correction = CalibrationCorrection(
            company_name=args.company,
            original_fit_score=args.original_score,
            corrected_fit_score=args.corrected_score,
            feedback=args.feedback,
        )
        calibration = append_calibration_entry(
            args.run,
            correction,
            preference_updates=args.preference or None,
        )
        print(calibration.model_dump_json(indent=2))
        return 0

    if args.command == "apply-evaluations":
        result = apply_calibration_to_evaluations(args.run)
        print(json.dumps(result.__dict__, indent=2))
        return 0 if result.corrections_applied > 0 or not result.skipped else 0

    if args.command == "propose-profile":
        print(export_proposal_json(args.run))
        return 0

    if args.command == "apply-profile":
        result = apply_profile_updates(args.run, confirm=args.confirm)
        print(json.dumps(result, indent=2))
        return 0 if result.get("success") or result.get("dry_run") else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
