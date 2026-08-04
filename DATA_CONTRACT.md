# Data Contract — Agentic v2

Defines file ownership, schemas, and merge rules. **Agents stage; Python canonicalizes.**

## File classes

### Human-owned (agents read-only)

| Path | Purpose |
|------|---------|
| `user/master_cv.md` | Full CV / resume source |
| `user/career_profile.md` | Summary background, domains, seniority |
| `user/proof_points.md` | Quantified achievements and evidence |
| `user/project_inventory.md` | Portfolio projects with tech stack |
| `user/voice_style.md` | Writing tone for future tailoring |
| `config/profile.yml` | Index of user files + preferences |
| `config/target_roles.yml` | Target job titles |
| `config/scoring_weights.yml` | Fit dimension weights |
| `config/sources.yml` | Discovery source index |
| `skills/*/SKILL.md` | Agent workflow instructions |

### System config (Python reads; agents read-only)

| Path | Purpose | Notes |
|------|---------|-------|
| `config/settings.yaml` | Paths, scraping, LLM defaults | Canonical for Python |
| `config/scoring.yaml` | Keyword scoring weights | Legacy alias of scoring_weights |
| `config/directory_sources.yaml` | Directory scrape definitions | Canonical for Python discovery |
| `config/job_keywords.yaml` | Role/domain keyword filters | Used by job discovery CLI |
| `config/job_board_sources.yaml` | Job board adapter catalog | Board discovery CLI |
| `config/job_discovery.yaml` | Budgets, triage settings | Job pipeline |
| `config/llm.yaml` | Ollama model settings | LLM scorer CLI |

### Agent staging (agents write; Python validates)

| Path | Format | Schema |
|------|--------|--------|
| `data/staging/company_candidates_<run_id>.json` | JSON array | `CompanyCandidate` |
| `data/staging/runs/<run_id>/company_candidates/<slug>.json` | JSON object | `CompanyCandidate` (preferred for event-driven merge) |
| `data/staging/company_evaluations_<run_id>.json` | JSON array | `CompanyFitResult` |
| `data/staging/runs/<run_id>/company_evaluations/<slug>.json` | JSON object | `CompanyFitResult` (preferred) |
| `data/staging/runs/<run_id>/manifest.json` | JSON object | Run metadata and counts |
| `data/staging/runs/<run_id>/calibration.json` | JSON object | `CalibrationFile` — user score corrections and preference themes |
| `data/staging/job_candidates_<run_id>.json` | JSON array | `JobCandidate` |
| `data/staging/job_evaluations_<run_id>.json` | JSON array | `JobFitResult` |
| `data/events/event_log.jsonl` | JSONL | Orchestration events (Python write) |
| `data/source_evidence/<run_id>/` | HTML, JSON, screenshots | Unstructured evidence |

`<run_id>` = ISO timestamp or UUID assigned at workflow start (e.g. `20250627T143000Z`).

### Canonical data (Python write only)

| Path | Format | Notes |
|------|--------|-------|
| `data/company_inventory.csv` | CSV | Master company list |
| `data/job_search.db` | SQLite | Jobs, companies, runs |
| `data/company_evaluations.csv` | CSV | Merged company fit scores (target) |
| `data/job_evaluations.csv` | CSV | Merged job fit scores (target) |
| `data/job_posts.csv` | CSV | Optional export of SQLite jobs |
| `data/scan_history.csv` | CSV | Run log export (target) |

**Legacy outputs** (still written by Python, will converge):

| Path | Maps to |
|------|---------|
| `outputs/company_fit_scores.csv` | `data/company_evaluations.csv` |
| `outputs/job_fit_scores.csv` | `data/job_evaluations.csv` |
| `outputs/directory_candidates.csv` | Staging preview |
| `outputs/job_discovery_results.csv` | Staging preview |

### Reports (Python or agent drafts)

| Path | Format |
|------|--------|
| `reports/company_fit/<slug>_<timestamp>.md` | Markdown evaluation report |
| `reports/job_fit/<slug>_<timestamp>.md` | Markdown evaluation report |

Agents may write report drafts; Python merge may copy validated JSON fields into CSV.

## Schemas

Pydantic models live in `src/schemas/` (re-exported from existing modules). See [src/schemas/README.md](src/schemas/README.md).

### Company inventory row (`data/company_inventory.csv`)

| Column | Type | Required | Notes |
|--------|------|----------|-------|
| `company_id` | int | auto | Assigned by Python on merge |
| `company_name` | string | yes | |
| `website` | url string | yes | Normalized by `src.discovery.link_utils` |
| `industry` | string | no | |
| `location` | string | no | |
| `size` | string | no | Startup / mid / large |
| `hiring_status` | string | no | |
| `priority` | string | no | High / Medium / Low |
| `last_checked` | iso date | no | |
| `source_id` | string | no | From directory source |
| `source_url` | url | no | |
| `source_category` | string | no | |
| `confidence` | float 0–1 | no | Discovery confidence |
| `notes` | string/json | no | |
| `career_page` | url or `NOT FOUND` | no | Added by career discovery |
| `career_page_status` | string | no | |
| `career_page_confidence` | float | no | |
| `career_page_checked_at` | iso datetime | no | |
| `career_page_notes` | string | no | |

### CompanyCandidate (discovery staging)

```json
{
  "company_name": "Example Bio Inc",
  "website": "https://example.com",
  "source_id": "life_sciences_bc",
  "source_name": "Life Sciences BC",
  "source_url": "https://lifesciencesbc.ca/member/example",
  "source_category": "Life Sciences BC Member",
  "confidence": 0.85,
  "notes": "optional"
}
```

Validated by `src.discovery.models.CompanyCandidate`. Merge: `src.discovery.update_inventory`.

### CompanyFitResult (evaluation staging)

```json
{
  "company_name": "Example Bio Inc",
  "fit_score": 7.5,
  "industry_alignment": 8.0,
  "mission_alignment": 7.0,
  "career_alignment": 7.5,
  "growth_potential": 6.5,
  "reasoning": "2-4 sentence summary",
  "best_roles": ["ML Scientist"],
  "interesting_factors": ["healthcare AI"],
  "red_flags": [],
  "confidence": 8.0
}
```

Validated by `src.llm.schemas.CompanyFitResult`.

### JobCandidate (job discovery staging)

```json
{
  "company_name": "Example Bio Inc",
  "title": "Machine Learning Scientist",
  "location": "Montreal, QC",
  "url": "https://example.com/jobs/ml-scientist",
  "description": "optional full text",
  "provider": "greenhouse",
  "source_career_page": "https://example.com/careers",
  "keyword_score": 0.4,
  "matched_keywords": ["machine learning", "python"]
}
```

Validated by `src.jobs.job_models.JobCandidate`. Persisted via `src.jobs.save_jobs`.

### SQLite `job_postings` row (canonical)

| Column | Type | Notes |
|--------|------|-------|
| `job_id` | int | Auto |
| `company_id` | int | FK → `companies`; auto-created for board discovery |
| `title` | string | Required |
| `location` | string | Optional |
| `url` | string | Normalized |
| `description` | string | Optional |
| `date_found` | iso datetime | Default now |
| `active` | bool/int | Default 1 |
| `fit_score` | float | **Agent evaluation only** (NULL until evaluated) |
| `fit_reason` | string | Agent evaluation summary |
| `source_board` | string | e.g. `jobbank`, `indeed_ca` |
| `discovery_run_id` | string | Board discovery run id |
| `keyword_score` | float 0–1 | Prescreen from `filter_jobs` |
| `matched_keywords` | JSON string | Keyword list |
| `evaluated_at` | iso datetime | Set when agent fit merge completes |

### JobFitResult (job evaluation staging)

```json
{
  "job_title": "Machine Learning Scientist",
  "company_name": "Example Bio Inc",
  "fit_score": 8.0,
  "skills_match": ["Python", "PyTorch"],
  "skill_gaps": ["clinical trials"],
  "recommended_actions": ["Highlight Mila postdoc"],
  "why_fit": "Strong ML + healthcare overlap",
  "concerns": [],
  "confidence": 7.5
}
```

Validated by `src.llm.schemas.JobFitResult`.

## Validation and merge flow

```
Agent output (staging JSON)
    → Pydantic parse (src/validators)
    → Dedup (src/discovery/deduplicate or src/jobs/save_jobs)
    → ID assignment / URL normalization (Python)
    → Write canonical CSV or SQLite
    → Append data/events/event_log.jsonl
    → Append scan_history / runs log
    → Export reports/ if applicable
```

On validation failure: reject file, log errors, do not partial-merge invalid rows.

## Modification rules

| Action | Allowed for agents |
|--------|-------------------|
| Edit `user/*` | No |
| Edit `data/company_inventory.csv` | No — use staging + Python merge |
| Edit `data/job_search.db` | No |
| Write `data/staging/*` | Yes |
| Write `data/source_evidence/*` | Yes |
| Write `reports/*` drafts | Yes (markdown only) |
| Edit `config/*.yaml` | No unless explicitly asked |
| Delete canonical data | No |

## Git exclusions

Not committed: `data/staging/*`, `data/source_evidence/*`, `data/cache/`, `data/raw/`, `*.db`, `outputs/*`, `.env`.

Seed file committed: `data/company_inventory.csv`.
