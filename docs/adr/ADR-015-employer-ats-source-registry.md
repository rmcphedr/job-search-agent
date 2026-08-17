# ADR-015: Employer ATS source registry

**Status:** Accepted  
**Date:** 2026-08-06  
**Deciders:** Project maintainer

## Context

Provider adapters can enumerate one known Greenhouse, Lever, Ashby, or Workday
employer board, but these ATS platforms are not global job boards. Treating them
only as transient career-page extractors makes them invisible in source health
and prevents independent scheduled refreshes.

## Decision

Store employer-specific ATS registrations in the Python-owned SQLite database.
Registrations are discovered from company career pages and existing authoritative
job URLs. A dedicated CLI refreshes registered sources, filters candidates using
the existing job configuration, and persists through `save_jobs`. ATS provider
health is displayed separately from configured third-party job boards.

Legacy jobs with an unambiguous ATS URL and blank source are backfilled with the
provider identifier during a non-dry source synchronization.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Add ATS providers to job-board YAML | Simple UI reuse | Misrepresents employer tenants as global boards |
| Re-scan all career pages every run | No registry | Slow and no persistent source health |
| SQLite employer-source registry | Durable, queryable, independently runnable | Adds a migration and synchronization step |

## Consequences

### Positive

- ATS employers become visible and independently refreshable.
- Existing job URLs can bootstrap the registry.
- Job validation, filtering, deduplication, and persistence remain unchanged.

### Negative / trade-offs

- Only known employers can be queried; there is no global ATS search feed.
- Embedded ATS discovery may require fetching employer career pages.

## Implementation notes

- Registry: `src/jobs/employer_ats_sources.py`
- Orchestration: `src/jobs/employer_ats_discovery.py`
- CLI: `python -m src.jobs.run_employer_ats_discovery`
- UI: Board Sources → Employer ATS sources

## Related

- ADR-010: deterministic board job discovery
- ADR-014: API-first employer ATS adapters
