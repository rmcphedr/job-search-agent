# Architectural Decision Records (ADR)

This directory records **significant, durable** technical and product architecture decisions. ADRs are the source of truth for *why* the system is built the way it is.

## When to write an ADR

Create or update an ADR when a decision:

- Changes data ownership, staging, or merge boundaries
- Introduces a new orchestration pattern (agents, events, CLIs)
- Chooses between competing storage, validation, or integration approaches
- Affects multiple skills, Python modules, or the dashboard
- Is hard to reverse without migration work

**Do not** write ADRs for routine bug fixes, refactors that preserve behavior, or style-only changes.

## Process

1. **Check** the [ADR index](#index) for an existing related ADR.
2. **Draft** a new file using the [template](template.md) (`ADR-NNN-short-title.md`).
3. **Number** sequentially — next available number in `docs/adr/`.
4. **Status**: start as `Proposed`; move to `Accepted` when implemented or agreed; `Superseded` when replaced (link to successor).
5. **Link** from PRDs, `AGENTS.md`, or `DATA_CONTRACT.md` when the decision affects those docs.
6. **On implementation**: update status to `Accepted` and note the implementing PR/commit if known.

## Rule for agents and maintainers

> **Whenever you make or implement a decision on a core feature**, add or update an ADR in `docs/adr/` before merging significant code. If the decision supersedes an older ADR, mark the old one `Superseded` and link both ways.

This rule is also enforced via `.cursor/rules/architectural-decisions.mdc`.

## ADR format

See [template.md](template.md). Required sections:

- **Title** — short noun phrase
- **Status** — Proposed | Accepted | Superseded | Deprecated
- **Context** — problem and constraints
- **Decision** — what we chose
- **Consequences** — positive, negative, and follow-ups

Optional: **Alternatives considered**, **Implementation notes**, **Related ADRs**.

## Index

| ID | Title | Status |
|----|-------|--------|
| [ADR-001](ADR-001-agentic-v2-split.md) | Agentic v2: agents judge, Python canonicalizes | Accepted |
| [ADR-002](ADR-002-staging-canonical-boundary.md) | Staging vs canonical data boundary | Accepted |
| [ADR-003](ADR-003-pydantic-schemas-as-contract.md) | Pydantic schemas as the data contract | Accepted |
| [ADR-004](ADR-004-sqlite-and-csv-storage.md) | SQLite + CSV dual storage model | Accepted |
| [ADR-005](ADR-005-skills-as-agent-workflows.md) | Skills as agent workflow specifications | Accepted |
| [ADR-006](ADR-006-ollama-legacy-scorer.md) | Ollama batch scorer as deterministic fallback | Accepted |
| [ADR-007](ADR-007-directory-discovery-python-fallback.md) | Python directory scraper as discovery fallback | Accepted |
| [ADR-008](ADR-008-hermes-event-driven-orchestration.md) | Hermes event-driven orchestration for discovery + evaluation | Accepted |
| [ADR-009](ADR-009-calibration-persistence.md) | Calibration persistence and preference learning | Accepted |
| [ADR-010](ADR-010-board-job-discovery.md) | Deterministic board job discovery with company auto-upsert | Accepted |
| [ADR-011](ADR-011-job-application-tracking.md) | Job application tracking in SQLite | Accepted |

## Related documents

- [Event-driven company pipeline PRD](../prd/event-driven-company-pipeline.md)
- [DATA_CONTRACT.md](../../DATA_CONTRACT.md)
- [AGENTS.md](../../AGENTS.md)
