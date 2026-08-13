# ADR-015: Quick-review decisions in SQLite

**Status:** Accepted  
**Date:** 2026-08-05  
**Deciders:** Project maintainer and coding agent  
**Supersedes:** None  
**Superseded by:** None

## Context

The dashboard needs a fast inbox for accepting, deferring, or declining high-fit
jobs. These decisions must survive refreshes without changing discovered job
records or conflating review state with the later application pipeline.

## Decision

Store one review decision per job in a canonical SQLite `job_reviews` table.
Python owns all CRUD. `accepted` records accompany creation of a `tracked_jobs`
row, `declined` jobs leave the inbox, and `maybe` jobs remain after unreviewed
jobs so they can be reconsidered.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Add a field to `job_postings` | Fewer tables | Mixes user workflow state with discovered source data |
| Store only in Streamlit session state | No migration | Decisions disappear after refresh or restart |
| Reuse `tracked_jobs` for all decisions | Existing storage | Declined and deferred jobs are not application pipeline entries |

## Consequences

### Positive

- Review state persists independently from discovery and evaluation.
- The application tracker remains limited to jobs the user chose to pursue.
- Future automated review can reuse the same explicit decision vocabulary.

### Negative / trade-offs

- Adds a schema migration and a small CRUD module.
- Accepting a job updates two tables and is not yet wrapped in one transaction.

### Follow-ups

- Add review-history analytics if calibration requires decision timestamps.
- Consider an atomic review-and-track service before automated applying.

## Implementation notes

Implemented by `src/database/job_reviews.py`, migration version 3, and
`src/ui/review_view.py`.

## Related

- ADRs: ADR-004, ADR-011, ADR-013
- Code: `src/database/job_reviews.py`, `src/ui/review_view.py`
