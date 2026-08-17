# ADR-018: Shared job-description enrichment and expiration

**Status:** Accepted  
**Date:** 2026-08-06  
**Deciders:** Project maintainer and coding agent  
**Supersedes:** None  
**Superseded by:** None

## Context

Most stored jobs lack descriptions, particularly aggregator leads. Discovery
had limited ATS-only enrichment and duplicate rediscovery did not repair empty
records. LinkedIn prohibits unauthorized automated scraping, while the review
and resume workflows require authoritative job text and a durable way to close
expired postings.

## Decision

Use one Python enrichment service during discovery and historical backfill.
Fetch ordinary posting URLs directly and use a bounded Playwright browser for
rendered LinkedIn and Eluta detail pages, then fall back to the employer's
known career page with title matching. Persist enrichment status, source URL, timestamp, and
failure reason. Deactivate a posting when an authoritative page returns 404,
410, an explicit expiration message, or the user marks it expired.

Backfill ordering prioritizes active, untracked, non-declined jobs already
eligible for the Review inbox, followed by other undecided jobs ranked by fit,
keyword score, and recency.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Scrape LinkedIn descriptions | Direct source | Violates platform restrictions; brittle and account-risking |
| Discovery-only enrichment | Prevents some new gaps | Leaves the existing backlog unresolved |
| Separate backfill implementation | Quick script | Logic and behavior drift from discovery |

## Consequences

### Positive

- New and existing jobs share identical provenance rules.
- Review and resume generation receive source-backed descriptions.
- Failed and expired jobs do not retry indefinitely.

### Negative / trade-offs

- Employer-career lookup can be slower and remains budgeted.
- Some aggregator-only jobs will remain unresolved and need manual input.

### Follow-ups

- Add a manual description paste/import action with provenance.
- Add provider-specific resolvers for high-volume aggregators.
- Re-run job-fit evaluation after descriptions are enriched.

## Implementation notes

- Service: `src/jobs/description_enrichment.py`
- Backfill CLI: `src/jobs/enrich_missing_descriptions.py`
- Discovery integration: `src/jobs/board_discovery/ats_enrich.py`

## Related

- ADRs: ADR-010, ADR-013
