# ADR-017: Resume pipeline request/result bridge

**Status:** Accepted  
**Date:** 2026-08-06  
**Deciders:** Project maintainer and coding agent  
**Supersedes:** None  
**Superseded by:** None

## Context

The job-search dashboard owns application state, while the sibling
`resume-generation-pipeline` owns richer career evidence, tailoring skills,
templates, and document builders. Copying these assets would introduce drift;
importing arbitrary code from another checkout would tightly couple runtimes.

## Decision

Integrate through a versioned JSON request/result contract and a subprocess
CLI. This repository stages requests and records results. The resume repository
stages the application folder, invokes its isolated Hermes `resume-agent`,
validates content, builds the DOCX, and returns artifact paths and warnings.
The canonical personal profile remains in the resume repository.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Copy skills/templates here | Self-contained | Duplicated evidence and template drift |
| Import sibling Python modules | Less process overhead | Fragile dependency and path coupling |
| JSON + CLI bridge | Explicit, testable boundary | Requires both repositories locally |

## Consequences

### Positive

- One dashboard controls the workflow without duplicating resume knowledge.
- Every generation run has an auditable request and result.
- Agent generation stays sandboxed inside the existing resume profile.

### Negative / trade-offs

- Resume generation is synchronous in the current Streamlit implementation.
- Local configuration must locate the sibling repository and Hermes profile.

### Follow-ups

- Move execution to a background worker and stream step status.
- Persist artifact metadata in normalized SQLite records if reporting expands.

## Implementation notes

- Dashboard adapter: `src/integrations/resume_pipeline.py`
- Resume CLI: `resume-generation-pipeline/scripts/generate-application.py`
- UI trigger: `src/ui/tracking_view.py`

## Related

- ADRs: ADR-012, ADR-016
