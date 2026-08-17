# ADR-016: Persistent application preparation checklist

**Status:** Accepted  
**Date:** 2026-08-06  
**Deciders:** Project maintainer and coding agent  
**Supersedes:** None  
**Superseded by:** None

## Context

A tracked job needs an inspectable transition from interest to application.
Preparation will eventually be performed by an agent, but the existing resume
tailoring skill is explicitly a placeholder and external submission is not yet
configured. The UI still needs durable, reviewable progress now.

## Decision

Represent preparation as ordered SQLite rows in
`application_preparation_steps`, owned by Python CRUD. Starting preparation
atomically creates the standard steps and moves the job to `applying`. Each
step records a status and inspectable details. Submission remains locked until
all steps are `complete` or `not_required`; the current submit control does not
send information externally.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Store checklist JSON on `tracked_jobs` | Simple schema | Harder to query, validate, and evolve |
| Session-only progress | Minimal implementation | Loses agent work and user review state |
| Submit directly from the first agent run | Fast automation | No review boundary and skill is not implemented |

## Consequences

### Positive

- Agent outputs and user review are visible per step.
- Progress survives dashboard restarts.
- The future application agent gets a stable persistence boundary.

### Negative / trade-offs

- Adds migration version 4 and another workflow table.
- External form discovery, resume generation, and submission still need agents.

### Follow-ups

- Implement and validate the resume-tailoring skill.
- Add an agent run model with evidence and artifact links per step.
- Require action-time user confirmation before external submission.

## Implementation notes

- Storage: `src/database/application_preparation.py`
- UI: `src/ui/tracking_view.py`
- Migration: `src/database/migrate.py` version 4

## Related

- ADRs: ADR-011, ADR-015
- Code: `DATA_CONTRACT.md`, `skills/resume_tailoring/SKILL.md`
