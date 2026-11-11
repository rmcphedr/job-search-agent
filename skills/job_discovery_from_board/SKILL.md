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
Set `provider` to the original board or ATS identifier and `source_channel`
to the discovery route when known. Use stable direct job URLs and keep
authoritative description evidence under `data/source_evidence/<run_id>/`.

## Evaluation (separate step)

After board discovery, run [job_fit_evaluation](../job_fit_evaluation/SKILL.md) on jobs where `evaluated_at IS NULL`. Hermes orchestration will trigger this in a later phase.

## Output schema

See [DATA_CONTRACT.md](../../DATA_CONTRACT.md) → JobCandidate.

## Merge

```bash
python -m src.jobs.run_board_discovery   # direct to SQLite
# or merge validated agent staging
python3 -m src.validators.merge --file data/staging/job_candidates_<run_id>.json
```

Do not bypass deduplication or edit `job_postings` directly.

### Bounded scheduled discovery

`python3 -m src.jobs.run_scheduled_discovery` checks enabled phase 1–2 boards
and registered employer ATS sources, then prints discovery run IDs and only
current-run jobs with verified descriptions that are ready for agent evaluation.
`--include-careers --career-limit 25` adds a rotating company-career pass with
legacy Ollama scoring disabled. ATS sync fetches at most 20 embedded career
pages and refreshes at most 50 registered employer boards per run. `--dry-run`
does not insert jobs or run logs.
This command does not claim or score evaluation work. Process selected job IDs
with the `daily-claim` and `submit` flow in `job_fit_evaluation`.

## Board phases

| Phase | Boards |
|-------|--------|
| 1 (enabled) | Job Bank, BioSpace, Bioinformatics.ca, NeuroTechX |
| 2 (enabled) | Life Sciences BC, CAN NeuroJobs, Health eCareers |
| 3 | LinkedIn, Indeed CA, Glassdoor, Google Jobs, Workopolis, Eluta, Wellfound, neurotechjobs.io |

Install Playwright before using phase 3 boards:

```bash
pip install playwright
playwright install chromium
```

### Sandbox probe (no DB writes)

Verify Playwright boards before a full discovery run:

```bash
# All enabled phase-3 boards
python -m src.jobs.board_discovery.playwright_sandbox --phase 3

# Single board
python -m src.jobs.board_discovery.playwright_sandbox --boards linkedin,eluta

# JSON output for CI
python -m src.jobs.board_discovery.playwright_sandbox --phase 3 --json
```

Per-board Playwright tuning lives in `config/job_board_sources.yaml` (`search_params.playwright_*`) and `config/settings.yaml` (`scraping.playwright`).

## ATS follow-through

Python enriches missing descriptions from authoritative posting pages and
employer career pages before saving, within the configured fetch budget. It
does not scrape LinkedIn detail pages; LinkedIn listings are resolved against
the employer's career page when possible.

Repair existing jobs with the same enrichment service:

```bash
python -m src.jobs.enrich_missing_descriptions --dry-run
python -m src.jobs.enrich_missing_descriptions --limit 25
python -m src.jobs.enrich_missing_descriptions --only-review-inbox
python -m src.jobs.enrich_missing_descriptions --only-review-inbox --retry-failed
python -m src.jobs.enrich_missing_descriptions --only-tracked --retry-failed
python -m src.jobs.enrich_missing_descriptions --mark-expired <job_id>
```

LinkedIn and Eluta detail pages use the configured Playwright browser by
default. Pass `--no-browser` only for HTTP/employer-site enrichment. Browser
blocks and navigation failures are stored as retryable `error` results.
