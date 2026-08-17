# ADR-013: Job evaluation SQLite merge

**Status:** Accepted  
**Date:** 2026-08-05  
**Deciders:** Project maintainer  
**Supersedes:** None  
**Superseded by:** None

## Context

Agent job evaluations were defined as staging JSON, and SQLite reserved `fit_score`, `fit_reason`, and `evaluated_at` for them, but the deterministic staging merger only supported company records. There was no safe path from an agent-produced `JobFitResult` to the canonical job row.

## Decision

Add optional `job_id` to `JobFitResult` and require it for SQLite-backed evaluation merges. Before updating anything, the Python merger validates the full batch and verifies each ID against the active job's exact title and company. A successful batch atomically updates the evaluation columns and emits one `job.evaluation.merged` event per job. The complete validated result is retained as JSON in `fit_details`; score, summary, and timestamp remain denormalized.

The merger also requires an enriched description with a recorded verification time. Authoritative expiration checks set the posting inactive and prevent evaluation, so fit work is not spent on known-closed roles.

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

- Structured evaluation details are stored as JSON rather than normalized child rows.

### Follow-ups

- Consider normalized child rows if structured fields later need independent querying.

## Implementation notes

- CLI: `python3 -m src.validators.merge --file data/staging/job_evaluations_<run_id>.json`
- Handler: `src.orchestration/handlers.py::merge_job_evaluation_file`

## Related

- ADRs: ADR-001, ADR-002, ADR-003, ADR-004
- Code: `src/llm/schemas.py`, `src/orchestration/handlers.py`
