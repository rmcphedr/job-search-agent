# ADR-022: Bounded discovery and source provenance

**Status:** Accepted  
**Date:** 2026-11-10  
**Deciders:** Project maintainer and coding agent

## Context

Configured job boards and employer ATS adapters had no routine execution path.
`source_board` mixed original providers with alert and feed routes, fragmenting
dashboard counts. Historical jobs must not enter scheduled evaluation implicitly.

## Decision

Add one bounded discovery CLI for enabled phase 1–2 boards and registered ATS
sources, with an optional rotating company-career pass. ATS sync caps embedded
page fetches at 20 and registered source refreshes at 50. The CLI reports one
shared discovery run ID and its description-verified, queued job IDs. It never starts
model evaluation. Agent staging of `JobCandidate` merges through the existing
Python validation and `save_jobs` boundary. Add `source_channel` to
`job_postings` and `JobCandidate`; retain canonical provider IDs in
`source_board`. Migrate known legacy alert and feed labels using Python schema
migrations. Board health requires a recent successful run, not just historical
jobs. Dry runs do not insert jobs or log runs to SQLite.

ATS boards inferred from existing job URLs are registered only when the board
identity matches the stored employer. This avoids expanding a shared parent
board under the wrong subsidiary name. Confirmed bad imports are deactivated
and their evaluation work cancelled through `src.jobs.import_quality`, with a
run-log entry preserving the review decision.

The existing stopped daily automation is not resumed by this change.

### Weekly full-board scope (2026-11-10 amendment)

At the user's request, `--all-boards` selects every enabled board, including
phase 3, for a Monday weekly scan. Disabled source stubs remain skipped and are
listed with that reason. The existing daily automation is repurposed as the
weekly scan; it imports through the Python pipeline but does not evaluate jobs.
Per-source failures must be reported so a partial scan is not mistaken for
complete coverage. Known browser challenge pages raise a persistent source
failure instead of appearing as an empty result. The bounded phase 1–2 default
remains available for manual runs. Boards with no results after queries are
reported as coverage warnings, since an empty parse does not prove there are
no current postings.
If the browser group cannot start, the scheduled CLI records those boards as
unattempted and still runs non-browser boards and ATS sources.

The first full pass exposed two parser quality gates: Indeed cards without an
application URL are discarded, and Workopolis employers and locations come
from their exact labeled fields. The affected imports were quarantined and
repaired through Python persistence rather than editing canonical data by hand.

## Alternatives considered

| Option | Trade-off |
|--------|-----------|
| Schedule every configured Playwright board | More apparent coverage, but brittle and restricted sources dominate failures. |
| Schedule bounded board and employer feeds | Reliable first pass, with restricted aggregators handled as leads or alerts. |

## Consequences

- The dashboard can show provider and discovery route separately.
- New job candidates have one supported staging merge command.
- Source health exposes stale and never-run boards.
- Scheduled evaluation remains an explicit bounded agent action per discovery run.

## Related

- ADR-010, ADR-015, ADR-018, ADR-020
- `src/jobs/run_scheduled_discovery.py`
