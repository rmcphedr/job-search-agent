# ADR-013: Job evaluation SQLite merge

**Status:** Accepted  
**Date:** 2026-08-05  
**Deciders:** Project maintainer  
**Supersedes:** None  
**Superseded by:** None

## Context

Agent job evaluations were defined as staging JSON, and SQLite reserved `fit_score`, `fit_reason`, and `evaluated_at` for them, but the deterministic staging merger only supported company records. There was no safe path from an agent-produced `JobFitResult` to the canonical job row.

## Decision

Add optional `job_id` to `JobFitResult` and require it for SQLite-backed evaluation merges. Before updating anything, the Python merger validates the full batch and verifies each ID against the active job's exact title and company. A successful batch atomically updates the three evaluation columns and emits one `job.evaluation.merged` event per job.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Match title and company only | No schema change | Ambiguous when duplicate postings exist |
| Let agents update SQLite | Minimal code | Violates the agent/Python ownership boundary |
| Verified `job_id` merge | Deterministic and auditable | SQLite-backed staging records must include an ID |

## Consequences

### Positive

- Agent evaluations now reach the canonical database safely.
- Identity mismatches reject the whole batch without partial updates.

### Negative / trade-offs

- Rich evaluation lists remain in staging JSON; SQLite currently stores only score, summary, and timestamp.

### Follow-ups

- Add canonical storage for structured matches, gaps, actions, concerns, and confidence if the dashboard needs them.

## Implementation notes

- CLI: `python3 -m src.validators.merge --file data/staging/job_evaluations_<run_id>.json`
- Handler: `src.orchestration/handlers.py::merge_job_evaluation_file`

## Related

- ADRs: ADR-001, ADR-002, ADR-003, ADR-004
- Code: `src/llm/schemas.py`, `src/orchestration/handlers.py`
