# ADR-001: Agentic v2 — agents judge, Python canonicalizes

**Status:** Accepted  
**Date:** 2025-06-27  
**Deciders:** Project maintainer

## Context

The original MVP was a Python-only pipeline: scrape directories, discover career pages, extract jobs, score with Ollama. Judgment-heavy tasks (evaluating company fit, interpreting sparse websites, choosing research direction) benefit from LLM agents with web access. Deterministic infrastructure (IDs, dedup, validation, storage) must remain reliable and auditable.

## Decision

Adopt **agentic-v2** architecture:

- **Agents** (Cursor skills / Hermes) perform discovery, evaluation, and ranking judgment; write only to staging and evidence paths.
- **Python** owns schemas, validation, deduplication, ID assignment, and all writes to canonical CSV/SQLite.

Document the split in `AGENTS.md` and `DATA_CONTRACT.md`.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Python-only with Ollama | Simple, reproducible | Weak web navigation; brittle for novel sources |
| Agents write canonical CSV directly | Fewer merge steps | No validation gate; duplicate/race risk |
| **Agents stage, Python merge** | Clear ownership; testable merge | Requires merge CLIs and event wiring |

## Consequences

### Positive

- Agents can use web search and judgment without corrupting inventory.
- Python merge remains unit-testable.

### Negative / trade-offs

- Two parallel paths existed initially (legacy CLIs bypass staging).
- Merge CLIs were deferred; staging bridge became MVP blocker.

### Follow-ups

- Implement staging merge CLIs (`src/validators/merge.py`).
- Event-driven orchestration (see ADR-008).

## Related

- [AGENTS.md](../../AGENTS.md)
- [DATA_CONTRACT.md](../../DATA_CONTRACT.md)
- ADR-002, ADR-005
