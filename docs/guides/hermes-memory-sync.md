# Hermes memory sync guidelines

How Hermes persistent memory should align with project files so preferences survive across sessions and stay auditable.

## Principle

**Repo files are the durable source of truth.** Hermes memory is a fast cache for conversational context. When they disagree, trust the repo.

## What to store where

| Information | Hermes memory | Repo file |
|-------------|---------------|-----------|
| Session run context (current `run_id`, companies in progress) | Yes | `data/staging/runs/<run_id>/manifest.json` |
| Score corrections for one run | Brief summary | `data/staging/runs/<run_id>/calibration.json` |
| Durable preference themes ("prefer product over consulting") | Yes (short bullets) | `user/agent_calibration.md` |
| Structured preferences (locations, industries, min scores) | Mirror only | `config/profile.yml` → `preferences` |
| Company evaluations | No | `data/company_evaluations.csv` |
| Evidence / research snippets | Optional pointers | `data/source_evidence/<run_id>/` |

## Write rules

1. **After calibration chat** — Hermes writes `calibration.json`, then runs:
   ```bash
   python -m src.orchestration.calibration_cli --run <run_id> apply-evaluations
   python -m src.orchestration.calibration_cli --run <run_id> propose-profile
   ```
2. **Profile themes** — only append to `user/agent_calibration.md` after user confirms:
   ```bash
   python -m src.orchestration.calibration_cli --run <run_id> apply-profile --confirm
   ```
3. **Never auto-edit** `user/master_cv.md`, `user/career_profile.md`, or `config/profile.yml` without explicit user approval.
4. **At start of each run** — read `user/agent_calibration.md` and latest `calibration.json` themes before discovery/evaluation.

## Memory hygiene

- Store **themes**, not full company lists (those live in CSV).
- After applying profile updates, store a one-line memory: "Applied calibration from run `<run_id>`."
- If memory conflicts with `agent_calibration.md`, re-read the file and correct memory.

## Related

- [Hermes orchestrator skill](../../skills/hermes_orchestrator/SKILL.md)
- [Event-driven pipeline PRD](../prd/event-driven-company-pipeline.md)
- [ADR-008](../adr/ADR-008-hermes-event-driven-orchestration.md)
