# ADR-010: Deterministic board job discovery with company auto-upsert

**Status:** Accepted  
**Date:** 2026-08-03  
**Deciders:** Project maintainer

## Context

Job discovery today is **company-career-page–first** (`run_job_discovery`). The user needs broad **Canada-focused** coverage across general job boards, life-sciences/neuro/health niche boards, and ATS-hosted postings discovered via aggregators (Eluta, Google Jobs, etc.).

Board-discovered employers are often **not** in `company_inventory.csv`. `save_jobs` previously skipped any job without a matching `companies` row.

Evaluation must remain a **separate agent step** (Cursor `job_fit_evaluation` skill now; Hermes orchestration later). Python only scrapes, prescreens, and persists.

## Decision

1. Add **`config/job_board_sources.yaml`** — canonical catalog of boards with `adapter`, `priority`, `phase`, and `enabled` flags.
2. Add **`src/jobs/board_discovery/`** — pluggable adapters; CLI `python -m src.jobs.run_board_discovery`.
3. **Auto-upsert companies** when a job references an unknown employer (`src/database/company_upsert.py`). Derive website from job URL domain when possible; otherwise use a deterministic placeholder `https://unresolved.local/{slug}`. Set `hiring_status = board_discovered` for later enrichment via company discovery.
4. Extend **`job_postings`** with `source_board`, `discovery_run_id`, `keyword_score`, `matched_keywords`, `evaluated_at`. Leave `fit_score` / `fit_reason` **NULL** until agent evaluation.
5. Reuse existing **`JobCandidate`**, **`filter_jobs`**, and ATS extractors in `job_extractors.py` when listings link to Greenhouse/Lever/Ashby/Workday/SmartRecruiters/iCIMS.
6. **Phased rollout** for anti-bot boards. LinkedIn, Indeed, Glassdoor, and Google
   Jobs use bounded Playwright adapters with static or structured-data parsers.
   Workopolis uses its accessible Canada search pages.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Agent-only board search | No scraper maintenance | Not deterministic; violates infra/agent split |
| Skip unknown companies | Simple | Loses most board results |
| Separate `board_companies` table | Clean separation | Complicates dashboard joins; rejected |

## Consequences

### Positive

- Single CLI for multi-board discovery aligned with user keywords in `job_keywords.yaml`
- Jobs visible in dashboard immediately; fit scores filled by agent later
- ATS adapters already exist for career pages; reused when board URLs point to ATS

### Negative / trade-offs

- Anti-bot boards may still return challenges and require parser maintenance
- Placeholder websites require company-discovery pass to replace with real domains
- High board count increases maintenance when HTML changes

### Follow-ups

- Phase 3: monitor Google Jobs markup and evaluate an official or paid API if the
  browser surface becomes unreliable
- Hermes event `board_jobs_discovered` → trigger `job_fit_evaluation` skill
- Merge CLI for `job_evaluations.csv` → update `job_postings.fit_score`

## Implementation notes

- Config: `config/job_board_sources.yaml`
- CLI: `src/jobs/run_board_discovery.py`
- Adapters: `src/jobs/board_discovery/adapters/`
- Company upsert: `src/database/company_upsert.py`
- Migrations: `src/database/migrate.py`
- PRD: `docs/prd/board-job-discovery.md`

## Related

- PRD: [board-job-discovery.md](../prd/board-job-discovery.md)
- ADRs: [ADR-002](ADR-002-staging-canonical-boundary.md), [ADR-004](ADR-004-sqlite-and-csv-storage.md)
- Skill: `skills/job_discovery_from_board/SKILL.md`
