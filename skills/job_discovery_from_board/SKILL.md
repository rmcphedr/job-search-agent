---
name: job-discovery-from-board
description: Discover jobs from external job boards (LinkedIn, Indeed, etc.). Secondary to website discovery. Output JobCandidate JSON to data/staging/.
---

# Job Discovery from Board

_Secondary skill — not in MVP critical path._

Discover roles from third-party job boards when company career pages are missing or incomplete.

## Read first

- [skills/job_discovery_from_website/SKILL.md](../job_discovery_from_website/SKILL.md) — prefer company sites first
- [config/target_roles.yml](../../config/target_roles.yml)
- [config/job_keywords.yaml](../../config/job_keywords.yaml)

## Your job

1. Search boards using role + location + domain keywords.
2. Match postings to companies in inventory when possible (`company_name` must align).
3. Output same `JobCandidate` JSON schema to `data/staging/job_candidates_<run_id>.json`.
4. Set `source_career_page` to the board search URL or listing page.
5. Note board-specific limitations (login walls, stale listings) in `notes`.

## Output

Same as website discovery — see [DATA_CONTRACT.md](../../DATA_CONTRACT.md) → JobCandidate.

## Merge

Python `src.jobs.save_jobs` after validation. Do not bypass deduplication.

## MVP status

Document-only. Use website discovery + Python CLI for MVP workflows.
