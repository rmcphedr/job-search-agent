# PRD: Board Job Discovery (Canada)

**Status:** In progress  
**Date:** 2026-08-03  
**ADR:** [ADR-010](../adr/ADR-010-board-job-discovery.md)

## Problem

Career-page discovery misses roles posted only on external boards. The user needs deterministic, keyword-driven scraping across general Canadian boards, domain-specific life-sciences/neuro/health boards, and ATS-backed listings — with jobs in SQLite and **separate** agent fit evaluation.

## Goals

| ID | Goal |
|----|------|
| G1 | Scrape configured boards using `job_keywords.yaml` + `target_roles.yml` |
| G2 | Canada-first location filtering |
| G3 | Auto-create `companies` rows for unknown employers |
| G4 | Persist jobs with `source_board`; `fit_score` NULL until agent evaluates |
| G5 | Dashboard: paginate jobs 20 per page |
| G6 | Evaluation via Cursor `job_fit_evaluation` skill (Hermes later) |

## Board catalog

### General (Canada)

| source_id | Priority | Phase |
|-----------|----------|-------|
| linkedin | Essential | 3 (Playwright) |
| indeed_ca | Essential | 1 |
| google_jobs | High | 3 |
| glassdoor | Medium | 3 |
| jobbank | High | 1 |
| workopolis | Medium | 2 |
| eluta | High | 1 |

### Life sciences

| source_id | Priority | Phase |
|-----------|----------|-------|
| biospace | Essential | 1 |
| biotalent_petridish | Essential | 2 |
| bioinformatics_ca | Essential | 1 |
| life_sciences_bc | Essential | 2 |

### Neuro / health

| source_id | Priority | Phase |
|-----------|----------|-------|
| sfn_neurojobs | Essential | 2 |
| can_neurojobs | Essential | 2 |
| neurotechx | Essential | 1 |
| digital_health_canada | Essential | 2 |
| healthcarecan | High | 2 |
| healthecareers | Medium | 2 |
| himss_jobmine | High | 2 |
| amia | High | 2 |

### Startups

| source_id | Priority | Phase |
|-----------|----------|-------|
| wellfound | Essential | 2 |

### ATS follow-through

When a listing URL matches Greenhouse, Lever, Ashby, Workday, SmartRecruiters, or iCIMS, optionally enrich description via existing `job_extractors` (phase 1: detect provider; phase 2: detail fetch).

## User stories

### US-1: Run board discovery

```bash
python -m src.jobs.run_board_discovery --location canada --boards jobbank,indeed_ca,biospace
```

Jobs land in `job_postings` with `source_board` set; companies auto-created when missing.

### US-2: Evaluate jobs (agent)

Agent runs `skills/job_fit_evaluation/SKILL.md` on unevaluated jobs (`evaluated_at IS NULL`), writes staging JSON; future merge updates `fit_score`.

### US-3: Browse jobs in dashboard

Jobs page shows 20 per page with filters for board, evaluation status, keywords.

## Non-goals

- LinkedIn/Google/Glassdoor in phase 1 (anti-bot)
- Replacing career-page discovery
- Resume tailoring

## Acceptance criteria (phase 2)

- [x] Life Sciences BC, CAN-ACN NeuroJobs, Health eCareers adapters
- [x] ATS description enrichment for Greenhouse/Lever/Ashby/Workday/SmartRecruiters/iCIMS URLs
- [ ] Playwright adapters for blocked boards (phase 3)
