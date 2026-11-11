# ADR-021: Approval-driven application worker

**Status:** Accepted
**Date:** 2026-11-11
**Deciders:** Project maintainer and coding agent
**Supersedes:** [ADR-019](ADR-019-human-reviewed-application-agent.md)

## Context

Multi-page applications and human handoffs outlive Streamlit reruns. The user
needs job-specific authorization, reusable progress, and protection against
duplicate submissions after ambiguous employer responses.

## Decision

Every eligible opportunity offers Fully automate and Draft for review regardless
of fit score. Each action enqueues one durable application run. Fully automate
records authorization to complete this job, including final submission when
readiness and provenance checks pass. Draft for review may navigate non-final
pages (which can save partial applications) but stops at a review packet. The
user must explicitly authorize completion before the worker can submit it.

A separate local `python -m src.orchestration.application_worker --watch` process
claims leased SQLite runs and owns browser navigation, answer drafting, and
resume generation. Streamlit only renders state and calls Python control APIs.
Visible isolated browser profiles support account, verification, MFA, CAPTCHA,
consent, unknown-answer, and unsupported-control handoffs. Resume re-inspects the
current page. The machine must remain awake; restarting recovers durable work,
but an expired portal session may need another handoff.

Agent drafts live in staging and are validated before Python updates canonical
fields. Generated documents never establish new facts. Sensitive disclosures
and legal claims need explicit facts or user action. Approval edits a particular
answer; it does not silently create a reusable fact.

Final submission records an attempt before clicking. Only reliable employer
confirmation creates the immutable submission snapshot and atomically marks
Applied. An ambiguous result becomes submission_uncertain, with no UI retry or
resume action. Explicit manual reconciliation remains available. Cancellation
stops local work and does not undo an employer's saved application.

## Consequences

- One active run per job, leases, bounded attempts, checkpoints, and provider
  handoffs survive dashboard reruns.
- Users can inspect mode, status, answers, evidence, documents, validation, pages,
  and outstanding requirements. Mode changes and cancellation are explicit.
- Operations groups counts and mean approval-to-latest-checkpoint/completion
  elapsed seconds by current status and provider.
- Browser profiles and evidence stay local and Git-ignored; passwords do not
  enter SQLite. Unsupported controls require user takeover.
- ADR-019's independent document editing and manual reconciliation remain;
  its synchronous browser path and mandatory separate final confirmation are
  superseded by the run-specific modes above.
