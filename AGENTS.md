# Job Search Agent — Agent Router

This project uses an **agentic-v2** architecture: coding agents perform judgment-heavy discovery and evaluation; Python handles deterministic infrastructure (schemas, validation, deduplication, storage, IDs, run logging, orchestration).

Read [DATA_CONTRACT.md](DATA_CONTRACT.md) before reading or writing any data file.

## Architecture layers

| Layer | Location | Who modifies |
|-------|----------|--------------|
| User / profile | `user/`, `config/profile.yml` | Human (candidate) |
| Agent skills | `skills/*/SKILL.md` | Maintainers |
| System config | `config/` | Human or maintainer |
| Canonical data | `data/*.csv`, `data/job_search.db` | **Python merge only** |
| Agent staging | `data/staging/`, `data/source_evidence/` | Agents write here |
| Reports | `reports/` | Python export; agents may write markdown drafts |
| Deterministic code | `src/` | Python |

## MVP workflow (run in order)

```
company_discovery → [Python merge] → company_fit_evaluation → job_discovery_from_website
  → [Python merge] → job_fit_evaluation → [Python rank] → shortlist
```

### Step 1 — Company discovery

**Skill:** [skills/company_discovery/SKILL.md](skills/company_discovery/SKILL.md)

Agent finds candidate companies from directory sources (`config/sources.yml` → `config/directory_sources.yaml`).

**Output:** JSON array or CSV in `data/staging/company_candidates_<run_id>.json` (or `.csv`).

**Python merge:**

```bash
# Existing CLI (directory scraping — deterministic fallback)
python -m src.discovery.run_directory_discovery --dry-run
python -m src.discovery.run_directory_discovery

# Validates candidates via src.discovery.models.CompanyCandidate,
# dedupes via src.discovery.deduplicate, merges via src.discovery.update_inventory
```

Agents must **not** edit `data/company_inventory.csv` directly.

### Step 2 — Company fit evaluation

**Skill:** [skills/company_fit_evaluation/SKILL.md](skills/company_fit_evaluation/SKILL.md)

Agent evaluates companies against `user/` profile files.

**Output:** JSON array in `data/staging/company_evaluations_<run_id>.json` matching `CompanyFitResult` schema.

**Python merge / export:**

```bash
# Legacy Ollama batch scorer (still works; agents may replace reasoning step)
python -m src.llm.score_companies --limit 5

# Validated exports land in outputs/company_fit_scores.csv
# Target canonical file: data/company_evaluations.csv (future merge CLI)
```

Detailed reports: `reports/company_fit/<company_slug>_<timestamp>.md`

### Step 3 — Job discovery from website

**Skill:** [skills/job_discovery_from_website/SKILL.md](skills/job_discovery_from_website/SKILL.md)

Agent (or Python scraper) extracts jobs from company career pages in inventory.

**Output:** JSON array in `data/staging/job_candidates_<run_id>.json` matching `JobCandidate` schema.

**Python merge:**

```bash
# Career page URL discovery (updates inventory columns)
python -m src.careers.update_inventory_career_pages --limit 50

# Job extraction + SQLite insert
python -m src.jobs.run_job_discovery --limit 50
```

Agents must **not** insert into SQLite directly.

### Step 4 — Job fit evaluation

**Skill:** [skills/job_fit_evaluation/SKILL.md](skills/job_fit_evaluation/SKILL.md)

Agent scores active jobs against the user profile.

**Output:** JSON in `data/staging/job_evaluations_<run_id>.json` matching `JobFitResult` schema.

**Python merge:**

```bash
python -m src.llm.score_jobs --limit 10
```

Reports: `reports/job_fit/<job_slug>_<timestamp>.md`

### Step 5 — Ranking

**Skill:** [skills/ranking/SKILL.md](skills/ranking/SKILL.md)

Python aggregates scores and produces a shortlist. Agents may propose rank adjustments in staging JSON; Python applies weights from `config/scoring_weights.yml`.

## Secondary skills (not in MVP path)

| Skill | Purpose |
|-------|---------|
| [job_discovery_from_board/SKILL.md](skills/job_discovery_from_board/SKILL.md) | Board-specific discovery (LinkedIn, Indeed, etc.) |
| [resume_tailoring/SKILL.md](skills/resume_tailoring/SKILL.md) | Placeholder — not implemented |

## Python module map (preserve — do not delete)

Existing modules remain the deterministic backbone:

| Target folder | Current module | Role |
|---------------|----------------|------|
| `src/schemas/` | Re-exports from `discovery/models`, `jobs/job_models`, `llm/schemas` | Canonical Pydantic models |
| `src/validators/` | Pydantic validation on models | Parse agent JSON before merge |
| `src/storage/` | `src/database/` | SQLite + CSV persistence |
| `src/dedup/` | `src/discovery/deduplicate.py`, `src/jobs/save_jobs.py` | Company and job dedup |
| `src/orchestration/` | `src/discovery/`, `src/careers/`, `src/jobs/`, `src/llm/` CLIs | Pipeline entry points |
| `src/cli/` | `python -m src.<module>` pattern | Same as orchestration |

## Prompt templates (legacy)

`prompts/*.md` remain for the Ollama Python scorer. Agent skills supersede these for Cursor agents but reference the same JSON schemas.

## Rules for agents

1. Read `user/` and `config/profile.yml` before any evaluation skill.
2. Write discovery/evaluation outputs to `data/staging/` only.
3. Return structured JSON matching schemas in `src/schemas/`.
4. Store raw evidence (HTML snippets, source URLs) under `data/source_evidence/<run_id>/`.
5. Never commit secrets, `.env`, or local DB/cache files.
6. Prefer reusing Python CLIs for merge steps rather than hand-editing canonical CSVs.

## Dashboard

The Streamlit dashboard (`app/dashboard.py`) continues to work against existing paths. It will adopt `data/company_evaluations.csv` and `reports/` in a later milestone.
