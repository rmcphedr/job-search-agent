# ADR-005: Skills as agent workflow specifications

**Status:** Accepted  
**Date:** 2025-06-27  
**Deciders:** Project maintainer

## Context

The MVP pipeline has five judgment-heavy steps. Prompts in `prompts/` served the Ollama batch scorer but did not encode full workflows (inputs, evidence, staging paths, handoffs). Cursor agents need repeatable, version-controlled instructions.

## Decision

- Define each MVP step as a **skill** in `skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`).
- Skills specify: read-first files, job steps, output format, schema reference, Python fallback CLI, next-step handoff.
- `AGENTS.md` acts as the router — ordered MVP workflow and rules.
- Secondary skills (`job_discovery_from_board`, `resume_tailoring`) stay out of the critical path until implemented.

Agent must read `user/` and `config/profile.yml` before evaluation skills.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Monolithic AGENTS.md only | One file | Unmaintainable as steps grow |
| **Per-step SKILL.md + router** | Modular; discoverable in Cursor | Requires keeping handoffs in sync |
| External playbook (Notion) | Non-dev friendly | Not versioned with code |

## Consequences

### Positive

- Each step is independently updatable.
- Skills align with `DATA_CONTRACT.md` staging names.

### Negative / trade-offs

- Skills referenced merge CLIs that did not exist yet at authoring time.
- Hermes sub-agents will map 1:1 to skills (ADR-008).

### Follow-ups

- Add `skills/hermes_orchestrator/SKILL.md` for chat-driven runs.
- Align all skill JSON examples with Pydantic models (ADR-003).

## Related

- [skills/](../../skills/)
- [AGENTS.md](../../AGENTS.md)
- ADR-001, ADR-008
