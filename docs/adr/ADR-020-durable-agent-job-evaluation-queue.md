# ADR-020: Durable agent job evaluation queue

**Status:** Proposed
**Date:** 2026-08-17
**Deciders:** Project maintainer
**Supersedes:** None
**Superseded by:** None

## Context

New jobs are persisted with no agent fit score, but job discovery does not
durably schedule evaluation. The generic event log and `fit_score IS NULL`
queries cannot represent claims, deferrals, retries, failures, budgets, or model
telemetry reliably. The local Ollama scorer is too slow to be the normal path,
and Codex token usage may be estimated rather than exposed exactly.

The existing architecture requires agents to make fit judgments and Python to
validate, merge, and own canonical state.

## Decision

Use a Python-owned SQLite queue with one current item per job. Discovery and
description lifecycle code create or transition queue items. A Codex worker
claims leased batches, stages `JobFitResult` output, and completes work only
through the existing validated SQLite merge.

Use `gpt-5.6-terra` with low reasoning for normal job evaluation. Escalate an
individual job to medium reasoning only for configured uncertainty or validation
conditions. Runs stop before exceeding their configured estimated-token or job
limit; unfinished work remains queued.

Store evaluation runs and attempts as structured SQLite telemetry. Label token
usage as measured, estimated, or unavailable, and calculate dollar estimates
only from explicitly configured model rates. Surface queue health and run/model
efficiency in an Operations page in the existing Streamlit dashboard.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| SQLite durable queue | Transactional claims, retries, budgets, and efficient dashboard queries | Adds schema and lifecycle transitions |
| Event log as queue | Reuses current JSONL events | Awkward claiming, retry, deduplication, and status queries |
| Query `fit_score IS NULL` | Minimal schema work | Cannot distinguish queued, deferred, claimed, or failed work |
| Ollama automatic scoring | No hosted-model usage | Slow and inefficient; bypasses the preferred agent workflow |

## Consequences

### Positive

- Jobs found without an active agent session are not lost.
- Evaluation is idempotent, recoverable, budget-aware, and observable.
- Agent judgment and deterministic canonicalization remain separate.
- A lightweight model policy avoids using frontier planning capacity for routine
  scoring.

### Negative / trade-offs

- Queue correctness depends on wiring every material job-description lifecycle
  transition.
- Codex token counts may remain estimates when runtime usage is unavailable.
- Streamlit can manage queue state but cannot reliably launch Codex workers.

### Follow-ups

- Evaluate a cheaper fallback model only after measured quality and efficiency
  data exists.
- Revisit the default batch size and confidence threshold after initial runs.

## Implementation notes

- Queue and telemetry: new SQLite migrations and repository modules under
  `src/database/` or `src/orchestration/`.
- Producers: `src/jobs/save_jobs.py` and description enrichment/expiration code.
- Consumer boundary: `skills/job_fit_evaluation/SKILL.md` plus a Python claim/run
  CLI.
- Canonical completion: `src/orchestration/handlers.py`.
- UI: new Operations page under `src/ui/`, registered in `app/dashboard.py`.

## Related

- Design: [Durable Job Evaluation Queue and Observability](../superpowers/specs/2026-08-17-durable-job-evaluation-queue-design.md)
- ADRs: ADR-001, ADR-002, ADR-006, ADR-008, ADR-010, ADR-013, ADR-018
- Code: `src/jobs/save_jobs.py`, `src/orchestration/handlers.py`
