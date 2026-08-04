---
name: job-discovery-from-board
description: Discover jobs from external job boards (LinkedIn, Indeed, niche boards). Output JobCandidate JSON to staging or run Python board discovery CLI.
---

# Job Discovery from Board

Discover roles from third-party job boards when company career pages are missing or incomplete.

## Read first

- [skills/job_discovery_from_website/SKILL.md](../job_discovery_from_website/SKILL.md) — prefer company sites when available
- [config/target_roles.yml](../../config/target_roles.yml)
- [config/job_keywords.yaml](../../config/job_keywords.yaml)
- [config/job_board_sources.yaml](../../config/job_board_sources.yaml)
- [docs/prd/board-job-discovery.md](../../docs/prd/board-job-discovery.md)

## Deterministic discovery (Python)

```bash
# All enabled phase-1 boards, Canada, keywords from job_keywords.yaml
python -m src.jobs.run_board_discovery

# Specific boards
python -m src.jobs.run_board_discovery --boards jobbank,indeed_ca,biospace,eluta

# Preview without DB writes
python -m src.jobs.run_board_discovery --dry-run -v
```

Python will:

1. Search boards using role + location + domain keywords
2. Prescreen with `filter_jobs` (keyword score, Canada location boost)
3. **Auto-create** `companies` rows for unknown employers (`hiring_status = board_discovered`)
4. Insert into `job_postings` with `source_board` set and `fit_score` NULL (pending agent evaluation)

## Agent staging (optional)

Agents may still write `JobCandidate` JSON to `data/staging/job_candidates_<run_id>.json` for manual curation before merge.

## Evaluation (separate step)

After board discovery, run [job_fit_evaluation](../job_fit_evaluation/SKILL.md) on jobs where `evaluated_at IS NULL`. Hermes orchestration will trigger this in a later phase.

## Output schema

See [DATA_CONTRACT.md](../../DATA_CONTRACT.md) → JobCandidate.

## Merge

```bash
python -m src.jobs.run_board_discovery   # direct to SQLite
# or
python -m src.jobs.save_jobs             # after staging validation
```

Do not bypass deduplication or edit `job_postings` directly.

## Board phases

| Phase | Boards |
|-------|--------|
| 1 (enabled) | Job Bank, BioSpace, Bioinformatics.ca, NeuroTechX |
| 2 (enabled) | Life Sciences BC, CAN NeuroJobs, Health eCareers |
| 3 (Playwright / TLS) | LinkedIn, Indeed, Eluta, Wellfound, PetriDish, SfN NeuroJobs, HIMSS, AMIA, Workopolis, neurotechjobs.io |

## ATS follow-through

When listings link to Greenhouse, Lever, Ashby, Workday, SmartRecruiters, or iCIMS, Python career extractors in `src/jobs/job_extractors.py` can enrich descriptions on detail fetch (future enhancement).
