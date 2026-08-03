# ADR-006: Ollama batch scorer as deterministic fallback

**Status:** Accepted  
**Date:** 2025-06-24  
**Deciders:** Project maintainer

## Context

Company and job fit evaluation require LLM reasoning. Agent-based evaluation (skills) is the target path for judgment and web research. A reproducible, local, non-agent fallback is still needed for batch runs, dashboard bootstrap, and environments without Cursor agents.

## Decision

- Keep **Phase 1 Ollama scorer** in `src/llm/score_companies.py` and `src/llm/score_jobs.py`.
- Configuration in `config/llm.yaml` (default model `qwen3:30b`).
- Prompt templates in `prompts/company_fit.md`, `prompts/job_fit.md`.
- Results cached under `data/cache/` and exported to `outputs/*_fit_scores.csv`.
- Agent skill evaluation **supersedes** Ollama for the same company when staging JSON is merged (future: prefer latest agent evaluation timestamp).

Agents are the preferred path for fit evaluation when Hermes orchestration is active (ADR-008).

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Cloud API only | Higher quality models | Cost; secrets; offline |
| **Local Ollama fallback + agent primary** | Free local batch; agent for quality | Two evaluation paths to reconcile |
| Remove Ollama entirely | Single path | No headless batch scoring |

## Consequences

### Positive

- Pipeline runnable without Cursor.
- Cached scores avoid redundant inference.

### Negative / trade-offs

- Dashboard may show SQLite `fit_score` from job discovery vs CSV from Ollama — disconnected until ranking CLI exists.
- Ollama export drops rich dimension fields.

### Follow-ups

- Merge agent evaluations to canonical CSV with full columns.
- Deprecate Ollama for company fit once Hermes evaluation is reliable.

## Related

- [src/llm/](../../src/llm/)
- [prompts/](../../prompts/)
- ADR-003, ADR-008
