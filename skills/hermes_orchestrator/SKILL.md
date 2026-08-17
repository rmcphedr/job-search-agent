---
name: hermes-orchestrator
description: Orchestrate event-driven company discovery and evaluation. Parse NL requests, manage runs, poll event log, delegate to sub-agents serially, present ranked results, capture calibration.
---

# Hermes Orchestrator

Top-level agent for the event-driven company discovery → evaluation pipeline. Uses persistent memory plus project files for preferences.

## Read first

- [docs/prd/event-driven-company-pipeline.md](../../docs/prd/event-driven-company-pipeline.md)
- [docs/adr/ADR-008-hermes-event-driven-orchestration.md](../../docs/adr/ADR-008-hermes-event-driven-orchestration.md)
- [AGENTS.md](../../AGENTS.md)
- [config/profile.yml](../../config/profile.yml)
- [user/career_profile.md](../../user/career_profile.md)
- [user/agent_calibration.md](../../user/agent_calibration.md) (if present)

## Sub-agents

| Task | Skill | When |
|------|-------|------|
| Discovery | [company_discovery/SKILL.md](../company_discovery/SKILL.md) | User request |
| Evaluation | [company_fit_evaluation/SKILL.md](../company_fit_evaluation/SKILL.md) | After each `company.merged` event (serial) |

## Start a run

1. Parse the user request (count, industries, locations, exclusions).
2. Assign `run_id` = ISO timestamp UTC, e.g. `20260801T183000Z`.
3. Initialize run:

```bash
python -m src.validators.merge --init-run <run_id> --request '{"count":50,"industries":["AI","healthcare"],"locations":["Montreal","Canada","Remote"]}'
```

4. Start the staging watcher (background terminal or ask user to run):

```bash
python -m src.orchestration.watch_staging
```

5. Delegate to **discovery sub-agent** with `run_id`, target count, and filters.

## Event poll loop (evaluation trigger)

After discovery begins, poll the event log for **one** `company.merged` event at a time:

```python
# Conceptual — read via shell or file read in agent
# data/events/event_log.jsonl
```

**Rules:**

- Process events **serially** — finish one evaluation before starting the next.
- Track `last_event_id` in the run manifest or session state.
- On `company.merged`:
  1. Check `data/company_evaluations.csv` — **skip** if company already evaluated (unless user asked to re-evaluate).
  2. Delegate to **evaluation sub-agent** for that company only.
  3. Sub-agent writes `data/staging/runs/<run_id>/company_evaluations/<slug>.json`.
  4. Watcher merges → `evaluation.merged` event.
  5. Repeat until no pending `company.merged` events for this run.

**Re-evaluation:** only when user explicitly says "re-evaluate &lt;company&gt;" — pass `force_re_eval` via merge CLI or instruct watcher with `--force-re-eval`.

## End-of-run chat output

When discovery is complete and all `company.merged` events have been evaluated (or skipped):

1. Read `data/company_evaluations.csv` for this run's companies.
2. Sort by `fit_score` descending.
3. Present summary table + reasoning + red flags.
4. Ask user to calibrate.

Example closing prompt:

> Here are 42 companies discovered and evaluated. Correct any scores or tell me what to weight differently next time.

## Calibration

After the user reviews ranked results:

1. Record corrections in `data/staging/runs/<run_id>/calibration.json` (or use CLI below).
2. Apply score overrides to canonical evaluations:
   ```bash
   python -m src.orchestration.calibration_cli --run <run_id> add-correction \
     --company "Acme Health AI" --original-score 8.0 --corrected-score 6.5 \
     --feedback "Too services-heavy" --preference "Prefer product companies"
   python -m src.orchestration.calibration_cli --run <run_id> apply-evaluations
   ```
3. Preview preference themes:
   ```bash
   python -m src.orchestration.calibration_cli --run <run_id> propose-profile
   ```
4. After user confirms, persist themes:
   ```bash
   python -m src.orchestration.calibration_cli --run <run_id> apply-profile --confirm
   ```

**Memory sync:** follow [docs/guides/hermes-memory-sync.md](../../docs/guides/hermes-memory-sync.md) — repo files are source of truth; Hermes memory stores short preference themes only.

- Per-score corrections → `calibration.json` → `data/company_evaluations.csv`
- Durable themes → `user/agent_calibration.md` (with `--confirm`)
- `config/profile.yml` → only update after explicit separate user approval

## Manual merge (fallback)

```bash
python -m src.validators.merge --file data/staging/runs/<run_id>/company_candidates/<slug>.json
python -m src.validators.merge --run <run_id>
python -m src.orchestration.watch_staging --once
```

## Python responsibilities (do not duplicate)

- Validate staging JSON (Pydantic)
- Merge to `data/company_inventory.csv` and `data/company_evaluations.csv`
- Append `data/events/event_log.jsonl`
- Update run manifest counts

Agents stage and evaluate; Python canonicalizes.
