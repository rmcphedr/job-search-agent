# ADR-003: Pydantic schemas as the data contract

**Status:** Accepted  
**Date:** 2025-06-27  
**Deciders:** Project maintainer

## Context

Agent outputs are JSON. Python merge and dashboard consumption require consistent field names, types, and score ranges. Ad-hoc dict parsing caused schema drift (e.g. `company_fit_score` vs `fit_score`, 0–1 vs 0–10 alignment scores).

## Decision

- Define canonical models in source modules (`src/discovery/models.py`, `src/jobs/job_models.py`, `src/llm/schemas.py`).
- Re-export from `src/schemas/` for agent documentation.
- Validate all staging input through Pydantic before merge (`src/validators/load_staging_file`).
- Document shapes in `DATA_CONTRACT.md` and `src/schemas/README.md`.
- On validation failure: reject record, log errors, do not merge.

Score conventions:

- Discovery `confidence`: 0–1 float
- Fit dimensions and `fit_score`: 0–10 float
- Fit `confidence`: 0–10 float (not categorical strings)

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| JSON Schema files only | Language-agnostic | Duplication with Python merge code |
| **Pydantic in Python + docs** | Single validation path | Agents must match Python field names |
| Loose merge with aliases | Tolerates agent drift | Hides skill bugs; harder to debug |

## Consequences

### Positive

- Merge code operates on typed objects.
- Skills can reference exact field names.

### Negative / trade-offs

- Agent skills must be kept in sync with models.
- Legacy staging samples may fail until normalized.

### Follow-ups

- Optional normalizer layer for common agent mistakes (defer unless needed).
- `ShortlistEntry` model for ranking staging (not yet implemented).

## Related

- [src/schemas/README.md](../../src/schemas/README.md)
- ADR-002, ADR-008
