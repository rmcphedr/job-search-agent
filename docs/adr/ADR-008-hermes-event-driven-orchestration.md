# ADR-008: Hermes event-driven orchestration for discovery and evaluation

**Status:** Accepted  
**Date:** 2026-08-01  
**Implemented:** 2026-08-01 (Phase 1–2: merge CLIs, event log, staging watcher)  
**Deciders:** Project maintainer  
**Supersedes:** (partial) manual handoffs described in ADR-005

## Context

The MVP workflow (company discovery → fit evaluation → job discovery → job fit → ranking) is documented as a linear manual sequence. The maintainer uses **Hermes** — a persistent-memory agent — as the primary interface. Goals:

1. Natural-language requests ("find 50 undiscovered AI health companies in Canada").
2. Automatic staging, per-record validation, and inventory merge without manual CLI steps.
3. Evaluation triggered when a new company enters the database.
4. Same chat session shows discovered companies, evaluations, ranking, and reasoning.
5. User calibration in chat updates preferences over time (Hermes memory + project files).

Current gaps: no merge CLIs, batch-only staging JSON, no event bus, no Hermes skill, schema drift in sample staging files.

## Decision

### Orchestration model

**Hermes** is the top-level orchestrator with persistent memory. It delegates to **sub-agents** mapped to existing skills:

| Sub-agent | Skill | Trigger |
|-----------|-------|---------|
| Discovery | `skills/company_discovery/SKILL.md` | User request or scheduled run |
| Evaluation | `skills/company_fit_evaluation/SKILL.md` | `company.merged` event (new inventory row) |
| (Future) Job discovery | `skills/job_discovery_from_website/SKILL.md` | User request or `company.evaluated` above threshold |
| (Future) Ranking | `skills/ranking/SKILL.md` | End of discovery+evaluation batch |

Hermes reads `user/`, `config/profile.yml`, and its own memory. It writes run manifests and calibration notes to agent-writable paths (see PRD § Preference learning).

### Staging: per-record incremental files

Move from batch-only JSON arrays to **one file per record** for event-friendly validation:

```
data/staging/runs/<run_id>/manifest.json
data/staging/runs/<run_id>/company_candidates/<slug>.json
data/staging/runs/<run_id>/company_evaluations/<slug>.json
```

Batch array files (`company_candidates_<run_id>.json`) remain supported for backward compatibility; merge CLI accepts both.

Each candidate file is validated immediately on write (schema + dedup check against inventory). Failed files go to `data/staging/runs/<run_id>/rejected/` with error sidecar.

### Event bus (Python)

Introduce `src/orchestration/` with:

1. **File watcher** (`watch_staging.py`) — watches `data/staging/runs/` for new JSON files.
2. **Merge handlers** — validate → dedup → `update_inventory()` or evaluation CSV merge.
3. **Event log** — append-only `data/events/event_log.jsonl` + SQLite `runs` row per event.

Event types (MVP):

| Event | Payload | Handler |
|-------|---------|---------|
| `candidate.staged` | path, run_id, company_name | Validate only (pre-merge) |
| `company.merged` | company_id, company_name, run_id | Queue evaluation sub-agent |
| `evaluation.staged` | path, run_id, company_name | Validate |
| `evaluation.merged` | company_name, fit_score, run_id | Notify Hermes / update run manifest |
| `run.completed` | run_id, counts | Hermes presents summary in chat |

### Trigger mechanism (decided 2026-08-01)

**Hybrid: durable event log + Hermes as serial consumer.** Cursor Automations are not the primary trigger.

| Layer | Role |
|-------|------|
| **Python watcher** (`watch_staging.py`) | Validates staging files, merges to canonical stores, **appends** `data/events/event_log.jsonl` |
| **Event log** | Source of truth for `company.merged`, `evaluation.merged`, etc.; survives chat restarts |
| **Hermes orchestrator** | Polls event log in the active chat; dequeues **one** `company.merged` at a time; spawns evaluation sub-agent |

Evaluation policy:

- **Serial:** one company evaluated per dequeue (no parallel evaluation sub-agents).
- **No re-eval:** skip companies already present in `data/company_evaluations.csv` unless the user explicitly requests re-evaluation (`force_re_eval` flag on merge CLI or orchestrator instruction).

Cursor Automations may be added later for ancillary tasks (e.g. start watcher on project open) but not for per-company evaluation.

Python never calls LLMs for evaluation in this path; it only validates, merges, and emits events.

### Interactive calibration

After a run, Hermes outputs a ranked table (fit_score, reasoning, red flags) in chat. User corrections are captured as:

- `data/staging/runs/<run_id>/calibration.json` — per-company overrides and free-text feedback
- `user/agent_calibration.md` — durable learnings Hermes may append (human can edit)
- Hermes persistent memory — session-spanning preference weights

Explicit user corrections may update `config/profile.yml` → `preferences` only after user confirms ("apply to profile").

### Chat output contract

End of discovery+evaluation run, Hermes produces:

1. Run summary (requested count, found, merged, rejected duplicates)
2. Ranked company list (fit_score desc)
3. Per-company: reasoning, best_roles, red_flags, confidence
4. Calibration prompt ("correct any scores or tell me what to weight differently")

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Manual CLI between steps | Simple; exists today | Not automatic; poor UX |
| Single long agent session writes CSV | No merge layer | Violates ADR-002 |
| **Per-record staging + file watcher + Hermes sub-agents** | Incremental validation; event triggers; memory | More moving parts |
| GitHub Actions on staging push | CI-native | Staging is gitignored; wrong tool |
| Python calls Ollama on merge | Fully automated | Loses agent web research; duplicates ADR-006 |

## Consequences

### Positive

- User can request discovery in natural language and get evaluated results in one chat.
- Validation at staging time catches schema errors before inventory pollution.
- Clear extension path for job discovery and ranking events.

### Negative / trade-offs

- Requires new `src/orchestration/` module and Hermes automation wiring.
- File watcher must be running (local daemon or Cursor automation).
- Two staging formats during migration.

### Follow-ups

- Phase 3: Hermes orchestrator skill + in-chat poll loop (see PRD).
- Phase 4: calibration persistence, dashboard reads `data/company_evaluations.csv`.
- Optional: Cursor Automation to launch watcher on project open.

### Implementation notes

- `src/validators/merge.py` — merge CLI for staging files and full runs
- `src/orchestration/events.py` — append-only event log
- `src/orchestration/manifest.py` — run manifest CRUD
- `src/orchestration/handlers.py` — candidate/evaluation merge + event emission
- `src/orchestration/watch_staging.py` — file watcher daemon
- `skills/hermes_orchestrator/SKILL.md` — poll loop and sub-agent delegation

## Related

- [Event-driven company pipeline PRD](../prd/event-driven-company-pipeline.md)
- ADR-001, ADR-002, ADR-003, ADR-005, ADR-006, ADR-007
