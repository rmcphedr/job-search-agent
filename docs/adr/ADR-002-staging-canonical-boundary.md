# ADR-002: Staging vs canonical data boundary

**Status:** Accepted  
**Date:** 2025-06-27  
**Deciders:** Project maintainer

## Context

Multiple writers (agents, Python CLIs, dashboard actions) touch company and job data. Without explicit boundaries, inventory corruption and partial merges are likely.

## Decision

| Class | Writers | Readers |
|-------|---------|---------|
| `data/staging/` | Agents only | Python merge |
| `data/source_evidence/<run_id>/` | Agents only | Agents + Python |
| `data/company_inventory.csv` | Python merge only | Agents (read-only), dashboard |
| `data/job_search.db` | Python only | Agents (read-only), dashboard |
| `data/company_evaluations.csv`, `data/job_evaluations.csv` | Python merge only | Agents, dashboard |
| `outputs/` | Python (legacy exports) | Dashboard, agents |
| `user/`, `config/` | Human (agents read-only unless calibration flow allows) | Agents, Python |

Staging files use `<artifact>_<run_id>.json` naming (batch) or per-record paths (see ADR-008). Invalid rows are rejected; no partial merge of failed validation.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Git-tracked staging | Visible history | Noise; PII risk |
| **Gitignored staging** | Clean repo; local runs | Requires merge to persist |
| Agents append to CSV | Simple | Race conditions; no schema gate |

## Consequences

### Positive

- Single choke point for canonical writes.
- Agents cannot accidentally delete or overwrite inventory.

### Negative / trade-offs

- Staging is local-only (gitignored); CI cannot see agent runs without artifacts.
- Merge CLIs must exist for every staging artifact type.

### Follow-ups

- Per-record staging for incremental validation (ADR-008).
- `scan_history` / `runs` table logging on each merge.

## Related

- [DATA_CONTRACT.md](../../DATA_CONTRACT.md)
- ADR-001, ADR-003, ADR-008
