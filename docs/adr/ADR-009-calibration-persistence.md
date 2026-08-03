# ADR-009: Calibration persistence and preference learning

**Status:** Accepted  
**Date:** 2026-08-01  
**Deciders:** Project maintainer  
**Related:** ADR-008

## Context

Phase 4 requires user score corrections and preference themes to persist beyond a single chat session and influence future discovery/evaluation runs. Evaluations live in `data/company_evaluations.csv`; preferences must not corrupt human-owned profile files without confirmation.

## Decision

1. **Run-scoped calibration** — `data/staging/runs/<run_id>/calibration.json` validated by Pydantic (`CalibrationFile`).
2. **Evaluation overrides** — applying calibration updates canonical CSV columns:
   - `original_fit_score`, `calibrated_fit_score`, `calibration_feedback`, `calibrated_at`
   - `fit_score` becomes the effective ranked score after apply.
3. **Preference themes** — append-only to `user/agent_calibration.md` via CLI with `--confirm` (no silent `config/profile.yml` edits).
4. **Hermes memory** — cache themes only; repo files are source of truth ([docs/guides/hermes-memory-sync.md](../guides/hermes-memory-sync.md)).
5. **CLI** — `python -m src.orchestration.calibration_cli` with subcommands:
   - `add-correction`, `apply-evaluations`, `propose-profile`, `apply-profile --confirm`

## Consequences

### Positive

- User corrections are auditable and versioned with the run.
- Dashboard ranks by calibrated scores when present.
- Profile files protected from accidental agent edits.

### Negative / trade-offs

- Extra CLI steps after chat calibration (can be scripted by Hermes).
- `config/profile.yml` structured preferences still manual unless future mapper is added.

## Implementation notes

- `src/orchestration/calibration.py`, `calibration_models.py`, `apply_preferences.py`, `calibration_cli.py`
- Dashboard: `Company Fit` page (`src/ui/evaluations_view.py`)
