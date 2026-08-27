# ADR-011: Job application tracking in SQLite

**Status:** Accepted  
**Date:** 2026-08-05  
**Deciders:** Maintainer + dashboard user

## Context

The dashboard surfaces discovered jobs (`job_postings`) but has no user-owned workflow state for applications. The user needs to save jobs from the sidebar, track them through pipeline stages (tracked → applying → applied → interviewing → accepted), and manage notes — without mixing that state into agent discovery or fit-evaluation fields.

Future phases will add qualification scoring, resume tailoring, and application auto-fill/submit from the same job detail surface.

## Decision

1. Add a SQLite table `tracked_jobs` keyed by `job_id` (FK → `job_postings`), with `stage`, `notes`, `applied_at`, and timestamps.
2. Python module `src/database/tracked_jobs.py` owns all CRUD; agents do not write this table.
3. Dashboard adds a **Tracking** page (default nav) with a main-area pipeline board by stage (teal-themed UI via `.streamlit/config.toml` + `src/ui/theme.py`). Job browsing stays on the **Jobs** tab.
4. Job detail view exposes the same track / stage controls.
5. Keep `tracked_jobs.stage` as the current-state snapshot and append every
   submitted-or-later transition to `application_stage_history`. Analytics use
   the history table so later outcomes do not erase earlier interview activity.
6. The initial post-submission state is displayed as **No response** (stored as
   `applied` for compatibility). A submitted application may then transition to
   interviewing, rejected, withdrawn, or accepted.

### Stages

`tracked` → `applying` → `applied` → `interviewing` → `accepted`  
Terminal: `rejected`, `withdrawn`

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| CSV `tracked_jobs.csv` | Human-editable | Poor joins with `job_postings`; rejected |
| Columns on `job_postings` | Simple query | Conflates discovery with user workflow; rejected |
| Separate `job_applications` with duplicate job fields | Offline from postings | Duplication and drift; rejected |

## Consequences

### Positive

- Clean separation: discovery data vs user pipeline state
- Joins keep company/title/url current when postings update
- Extensible for future resume/application features on same `job_id`
- Historical funnels and interview counts remain accurate after an application closes

### Negative / trade-offs

- Requires migration on existing databases
- Streamlit sidebar job list capped (50 active jobs) for responsiveness

### Follow-ups

- Fit score panel on tracking detail (agent evaluation merge)
- Resume tailoring + application auto-fill (separate PRD)
- Analytics funnel chart for pipeline conversion

## Implementation notes

- Schema: `src/database/schema.sql`; tracked jobs migration v2 and stage-history migration v12 in `src/database/migrate.py`
- CRUD: `src/database/tracked_jobs.py`
- UI: `src/ui/tracking_view.py`, `src/ui/theme.py`
- Entry: `app/dashboard.py` — **Tracking** first in navigation

## Related

- PRD: (future) application automation
- ADRs: [ADR-004](ADR-004-sqlite-and-csv-storage.md), [ADR-002](ADR-002-staging-canonical-boundary.md)
- Code: `DATA_CONTRACT.md` → `tracked_jobs` section
