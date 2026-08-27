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
    daily = sub.add_parser("daily-claim")
    daily.add_argument("--run-id", required=True)
    daily.add_argument("--discovery-run-id", required=True)
    daily.add_argument("--job-ids", required=True)
    daily.add_argument("--worker-id", required=True)
    daily.add_argument("--model", default="gpt-5.6-luna")
    daily.add_argument("--reasoning", default="low")
    daily.add_argument("--max-jobs", type=int, default=5)
    daily.add_argument("--token-limit", type=int, default=30_000)
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
    elif args.command == "daily-claim":
        job_ids = list(dict.fromkeys(int(value) for value in args.job_ids.split(",")))
        hard_limit = min(args.max_jobs, 5)
        if not 1 <= len(job_ids) <= hard_limit:
            raise ValueError(f"daily selection must contain between 1 and {hard_limit} unique jobs")
        base = load_evaluation_policy()
        policy = base.model_copy(update={
            "default_model": args.model,
            "normal_reasoning_effort": args.reasoning,
            "max_jobs_per_run": hard_limit,
            "batch_size": hard_limit,
            "estimated_token_limit": args.token_limit,
        })
        start_run(args.run_id, policy=policy, trigger="scheduled_daily")
        packet = claim_evaluation_packet(
            args.run_id,
            args.worker_id,
            policy=policy,
            job_ids=job_ids,
            discovery_run_id=args.discovery_run_id,
        )
        result = asdict(packet) if packet else None
    else:
        payload = json.loads(args.file.read_text()); result = asdict(submit_job_evaluations(args.run_id, [int(x) for x in args.queue_ids.split(',')], payload, model=args.model, reasoning_effort=args.reasoning))
    print(json.dumps(result, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
