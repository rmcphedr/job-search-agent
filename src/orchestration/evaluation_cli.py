"""CLI for explicit, budgeted agent job evaluation operations."""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from src.orchestration.evaluation_policy import load_evaluation_policy
from src.orchestration.evaluation_submission import submit_job_evaluations
from src.orchestration.evaluation_worker import claim_evaluation_packet, start_run
from src.orchestration.job_evaluation_queue import queue_summary
from src.ui.operations_data import enroll_backlog, preview_backlog


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(); sub = root.add_subparsers(dest="command", required=True)
    preview = sub.add_parser("backlog-preview"); preview.add_argument("--limit", type=int, default=10); preview.add_argument("--verified-only", action="store_true")
    enroll = sub.add_parser("backlog-enroll"); enroll.add_argument("--job-ids", required=True); enroll.add_argument("--max-jobs", type=int, required=True); enroll.add_argument("--token-limit", type=int, required=True); enroll.add_argument("--confirm", action="store_true")
    claim = sub.add_parser("claim"); claim.add_argument("--run-id"); claim.add_argument("--worker-id", required=True)
    submit = sub.add_parser("submit"); submit.add_argument("--run-id", required=True); submit.add_argument("--queue-ids", required=True); submit.add_argument("--file", type=Path, required=True); submit.add_argument("--model", default="gpt-5.6-terra"); submit.add_argument("--reasoning", default="low")
    sub.add_parser("status")
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.command == "status": result = queue_summary()
    elif args.command == "backlog-preview": result = [asdict(r) for r in preview_backlog(limit=args.limit, verified_only=args.verified_only)]
    elif args.command == "backlog-enroll": result = {"enrolled": enroll_backlog([int(x) for x in args.job_ids.split(',')], confirm=args.confirm, max_jobs=args.max_jobs, token_limit=args.token_limit)}
    elif args.command == "claim":
        run_id = args.run_id or str(uuid.uuid4()); policy = load_evaluation_policy(); start_run(run_id, policy=policy)
        packet = claim_evaluation_packet(run_id, args.worker_id, policy=policy); result = asdict(packet) if packet else None
    else:
        payload = json.loads(args.file.read_text()); result = asdict(submit_job_evaluations(args.run_id, [int(x) for x in args.queue_ids.split(',')], payload, model=args.model, reasoning_effort=args.reasoning))
    print(json.dumps(result, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
