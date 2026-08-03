# Documentation

Project planning, product requirements, and architectural decision records.

| Section | Purpose |
|---------|---------|
| [prd/](prd/) | Product requirements and implementation plans |
| [adr/](adr/) | Architectural Decision Records (ADRs) — **update when core features are decided** |
| [guides/](guides/) | Operational guides (Hermes memory sync, etc.) |

## Quick links

- [Event-driven company discovery PRD](prd/event-driven-company-pipeline.md) — Hermes orchestration, staging, merge, evaluation
- [Hermes memory sync guide](guides/hermes-memory-sync.md)
- [ADR index & process](adr/README.md) — how to write and maintain ADRs
- [Agent router](../AGENTS.md) — MVP workflow
- [Data contract](../DATA_CONTRACT.md) — staging vs canonical ownership

## When to add docs

| Trigger | Document |
|---------|----------|
| New product capability or workflow change | PRD in `docs/prd/` |
| Core architecture or ownership decision | ADR in `docs/adr/` (see [ADR process](adr/README.md)) |
| Skill behavior change that affects data flow | Update relevant ADR + `DATA_CONTRACT.md` |
