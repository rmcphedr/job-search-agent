# ADR-004: SQLite + CSV dual storage model

**Status:** Accepted  
**Date:** 2025-06-24 (evolved through 2025-06-27)  
**Deciders:** Project maintainer

## Context

Company inventory is human-editable and dashboard-friendly as CSV. Job postings, runs, and relational queries fit SQLite better. The MVP needed both browseable company lists and structured job storage without operating a server database.

## Decision

| Data | Primary store | Notes |
|------|---------------|-------|
| Company inventory | `data/company_inventory.csv` | Seed in git; career page columns added by Python |
| Job postings | `data/job_search.db` → `job_postings` | Active flag, fit_score, dedup by URL |
| Companies (DB mirror) | `data/job_search.db` → `companies` | Synced from inventory import |
| Run history | `data/job_search.db` → `runs` | Pipeline audit trail |
| Fit evaluations (target) | `data/company_evaluations.csv`, `data/job_evaluations.csv` | Canonical; legacy in `outputs/` |
| Fit evaluations (legacy) | `outputs/company_fit_scores.csv`, `outputs/job_fit_scores.csv` | Subset columns; still used by dashboard helpers |

Python CLIs read inventory CSV and write jobs to SQLite. Dashboard reads both.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| CSV only | Simple | Poor job dedup and history |
| SQLite only | Relational | Harder hand-editing of company list |
| **CSV inventory + SQLite jobs** | Best of both | Two sources; sync on import |

## Consequences

### Positive

- Streamlit dashboard works against familiar files.
- Job pipeline has proper dedup and run logging.

### Negative / trade-offs

- Company data can drift between CSV and SQLite `companies` until import/sync.
- Evaluation CSVs not yet fully wired (legacy `outputs/` still primary).

### Follow-ups

- Merge CLIs write canonical evaluation CSVs with full schema columns.
- Optional `data/job_posts.csv` export from SQLite.

## Related

- [src/database/](../../src/database/)
- ADR-001, ADR-002
