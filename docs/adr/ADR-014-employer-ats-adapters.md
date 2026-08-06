# ADR-014: API-first employer ATS adapters

## Status

Accepted

## Context

Employer career pages commonly delegate listings to Greenhouse, Lever, Ashby, or
Workday. Their browser pages are frequently JavaScript-rendered, so generic HTML
link extraction misses listings or produces incomplete metadata.

## Decision

Job discovery uses provider-specific, read-only public ATS endpoints before HTML
extraction for Greenhouse, Lever, Ashby, and Workday. Each adapter maps provider
payloads into a small provider-neutral `ATSJob` value. The existing extractor then
creates canonical `JobCandidate` models, preserving validation, filtering,
deduplication, and SQLite ownership boundaries.

Adapter errors return no results and allow the existing HTML/portal fallback to
run. Workday requests are paginated with a fixed upper bound to prevent unbounded
discovery runs.

## Consequences

- Listings from JavaScript-heavy ATS pages can be discovered deterministically.
- Provider payload differences are isolated from the rest of job discovery.
- Upstream, undocumented public endpoint changes may require adapter maintenance.
- The existing generic HTML extraction remains available during provider outages.
