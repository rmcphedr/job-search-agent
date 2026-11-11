# ADR-021: Staged company-priority override

**Status:** Accepted  
**Date:** 2026-09-29  
**Deciders:** Maintainers

## Context

The company inventory displays a priority field, but new `CompanyCandidate`
records previously derived it only from discovery confidence. A user could ask
to make a company top priority, yet the agent could not express that request
through the validated staging boundary.

## Decision

Add an optional `priority` field to `CompanyCandidate`, constrained to `High`,
`Medium`, or `Low`. Python's inventory merger remains the only canonical-data
writer. When supplied, the staged value is used for an inserted company and
may raise an existing company's priority; omitted values retain the existing
confidence-derived default.

## Consequences

Agents can faithfully stage explicit user priority decisions without editing
the canonical CSV. Invalid priorities are rejected at validation time. The
field does not introduce new storage or orchestration paths.
