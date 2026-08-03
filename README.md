# Job Search Agent

A Python-based job-search intelligence agent for discovering, tracking, and scoring opportunities at AI, healthcare, neuroscience, and biotech companies.

## Agentic v2 architecture

This branch shifts **judgment and web navigation** to Cursor agent skills while keeping **Python** for schemas, validation, deduplication, storage, and orchestration.

| Layer | Location |
|-------|----------|
| Agent router | [AGENTS.md](AGENTS.md) |
| Data contract | [DATA_CONTRACT.md](DATA_CONTRACT.md) |
| PRDs & ADRs | [docs/](docs/) |
| User profile | [user/](user/) |
| Agent skills | [skills/](skills/) |
| Staging outputs | `data/staging/`, `data/source_evidence/` |
| Deterministic code | [src/](src/) (unchanged modules) |

**Hermes orchestration (planned):** [Event-driven company pipeline PRD](docs/prd/event-driven-company-pipeline.md) — natural-language discovery, per-company staging, automatic merge, and evaluation triggers.

**MVP workflow:** company discovery → Python merge → company fit evaluation → job discovery from website → Python merge → job fit evaluation → ranking.

Start with [AGENTS.md](AGENTS.md). Agents write JSON to `data/staging/`; Python CLIs merge into `data/company_inventory.csv` and SQLite. Legacy `outputs/` and `prompts/` remain for the Ollama scorer and dashboard.

## Description

This project helps prioritize job search efforts by maintaining a company inventory, scraping career pages, storing structured job data, and scoring role fit against configurable criteria. It is designed as a portfolio-ready pipeline that can be extended with LLM enrichment and a Streamlit dashboard.

## MVP Goal

Build a working end-to-end pipeline that:

1. Reads a curated list of target companies from `data/company_inventory.csv`
2. Scrapes company career pages and stores raw HTML in `data/raw/`
3. Persists structured company and job records in a local SQLite database
4. Scores each role for fit based on domain, ML, healthcare/biotech, location, and hiring signals
5. Exports ranked results to `outputs/` for review

## Planned Features

- **Company inventory management** — CSV-driven list of target companies with priority and hiring status
- **Web scraping** — Career page discovery and job listing extraction
- **Data storage** — SQLite database for companies, jobs, and scrape history
- **LLM enrichment** — Optional summarization and keyword extraction via OpenAI, Anthropic, or Ollama
- **Fit scoring** — Weighted scoring against configurable keywords, roles, and locations
- **Streamlit dashboard** — Interactive view of ranked opportunities and company status

## Tech Stack

- **Python 3**
- **pandas** — Data manipulation and CSV handling
- **requests** + **BeautifulSoup4** — HTTP scraping and HTML parsing
- **pydantic** — Data validation and settings models
- **PyYAML** — Configuration files
- **python-dotenv** — Environment variable management
- **Streamlit** — Dashboard UI
- **SQLite** — Local database for companies, pages, profiles, jobs, and runs

## Setup

```bash
# Clone the repository
git clone <repo-url>
cd job-search-agent

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template and fill in API keys (optional for MVP)
cp .env.example .env
```

Configuration lives in `config/settings.yaml` (paths, LLM, scraping) and `config/scoring.yaml` (weights, target keywords, roles, locations).

## Database Setup

Initialize the local SQLite database, import the seed company inventory, and inspect the result:

```bash
python -m src.database.init_db
python -m src.database.import_inventory
python -m src.database.inspect_db
```

The database file is written to `data/job_search.db`. It is local-only and excluded from GitHub by `.gitignore` (`*.db`).

## Directory Discovery

Discover companies from curated directory pages (BIOTECanada, CDL, Life Sciences BC, MaRS, Centech, Neurotech Jobs) and populate `data/company_inventory.csv` with company names and best-known website/profile URLs.

This stage only scrapes **directory source pages** — it does not yet scrape individual company About or Careers pages. Raw scraped HTML is not stored at this stage; extracted candidates are written to `outputs/directory_candidates.csv`.

**Life Sciences BC** uses a two-step extraction:

1. Scrape the [alphabetical member listing](https://lifesciencesbc.ca/membership/members-directory/alphabetical-listing/)
2. Follow each member profile page to extract the external company website and profile metadata

```bash
python -m src.discovery.run_directory_discovery --dry-run
python -m src.discovery.run_directory_discovery --source centech --dry-run
python -m src.discovery.run_directory_discovery --source creative_destruction_lab --dry-run
python -m src.discovery.run_directory_discovery
python -m src.discovery.debug_source --source life_sciences_bc --max-links 50
python -m src.discovery.test_source --source life_sciences_bc --limit 10
```

## Career Page Discovery

Find company career/jobs pages from the `website` column in `data/company_inventory.csv`.

This step:
- Checks common career paths (`/careers`, `/jobs`, `/join-us`, etc.)
- Scans homepage links for careers/jobs language
- Recognizes external ATS systems (Greenhouse, Lever, Ashby, Workday, BambooHR, and others)
- Writes `career_page = NOT FOUND` when no page is detected
- Does **not** extract individual job postings yet

```bash
python -m src.careers.update_inventory_career_pages --limit 10 --dry-run
python -m src.careers.update_inventory_career_pages --company "Valence Labs" --force
python -m src.careers.update_inventory_career_pages --limit 50 --sleep 1
```

## Job Discovery

Discover open job postings from `career_page` URLs in `data/company_inventory.csv`, filter by role/domain/technical keywords, and insert matching jobs into SQLite `job_postings` without duplicates.

The pipeline:
- Reads `career_page` from the company inventory (skips empty/`NOT FOUND` values)
- Detects known ATS providers when possible (Greenhouse, Lever, Ashby, Workday, BambooHR, etc.)
- Falls back to generic HTML link extraction
- Filters jobs using `config/job_keywords.yaml`
- Inserts new jobs with `active=1` and skips duplicates across runs

```bash
python -m src.jobs.run_job_discovery --limit 10 --dry-run
python -m src.jobs.run_job_discovery --company "Valence Labs" --dry-run
python -m src.jobs.debug_jobs_page --company "Valence Labs"
python -m src.jobs.run_job_discovery --limit 50 --sleep 1
python -m src.database.inspect_db
```

This stage extracts job listings and details only. It does not apply to jobs, send emails, or use LLM calls.

## LLM Fit Scoring (Phase 1)

Score companies and jobs against a structured candidate profile using a local Ollama model. Results are cached on disk and exported to CSV for dashboard integration.

**Requirements:**

- [Ollama](https://ollama.com/) running locally
- Model installed: `qwen3:30b` (configured in `config/llm.yaml`)

**Verify Ollama is running:**

```bash
ollama list
curl http://localhost:11434/api/tags
```

**Score companies** (reads `data/company_inventory.csv`):

```bash
python -m src.llm.score_companies --limit 5
python -m src.llm.score_companies --company "Valence Labs"
python -m src.llm.score_companies --force-refresh
```

**Score jobs** (reads active jobs from SQLite):

```bash
python -m src.llm.score_jobs --limit 10
python -m src.llm.score_jobs --company "Valence Labs"
python -m src.llm.score_jobs --force-refresh
```

**Outputs:**

- `outputs/company_fit_scores.csv` — company_name, fit_score, reasoning, confidence, timestamp
- `outputs/job_fit_scores.csv` — job_title, company_name, fit_score, skills_match, skill_gaps, confidence, timestamp
- `data/cache/company_fit/` and `data/cache/job_fit/` — cached JSON results (skipped when content unchanged)

**Configuration:** `config/llm.yaml` (provider, model, temperature, batch size, cache toggle)

**Prompt templates:** `prompts/company_fit.md`, `prompts/job_fit.md`

**Dashboard helpers** (for future UI integration):

```python
from src.llm import load_company_fit_scores, load_job_fit_scores
```

Phase 1 does not include resume tailoring, cover letters, outreach generation, or database schema changes.

## Dashboard

Launch the Streamlit dashboard to browse companies and jobs, run discovery pipelines, and review configuration:

```bash
streamlit run app/dashboard.py
```

### Views

- **Companies** — inventory with career page and job search status, filters, sorting, pipeline actions, and company detail pages
- **Jobs** — SQLite job postings with filters, keyword search, and job detail pages
- **Analytics** — portfolio metrics, charts, top opportunities, and recent jobs
- **Profile / Settings** — read-only display of `job_keywords.yaml`, `scoring.yaml`, and `settings.yaml`

### Dashboard actions

On the **Companies** page:

| Action | Description |
|--------|-------------|
| **Find Career Pages** | Runs career page discovery for selected companies and updates `company_inventory.csv` |
| **Run Job Discovery** | Extracts and inserts matching jobs into SQLite for selected companies |
| **Refresh Dashboard** | Reloads CSV and database data without restarting Streamlit |
| **Export Filtered Companies** | Downloads the currently filtered company table as `filtered_companies.csv` |

On the **Companies** page, check the box beside each company name in the list, then click **Find Career Pages** or **Run Job Discovery**. Use **Select all shown** or **Clear selection** to bulk-select the filtered list. Enable **Force re-check existing career pages** to overwrite existing career page values.

After actions complete, the dashboard refreshes automatically and shows summary metric cards plus recent run history.

### Company detail page

On **Companies**, choose a company from **Open company profile** and click **View Company** to open the detail page. You can also open companies from global search results in the sidebar.

The company detail page shows:

- Overview fields (website, industry, location, priority, hiring status, career/job status)
- Company health indicator (🟢 Healthy, 🟡 Partial, 🔴 Missing)
- Metadata from inventory notes (description, specialties, source directory, confidence)
- All jobs discovered for that company
- Recent discovery activity from the `runs` table
- Disabled **Coming Soon** placeholders for resume tailoring, cover letters, outreach, and application tracking

### Job detail page

On **Jobs** or from a company detail page, select a job and click **View Job Detail**.

The job detail page shows title, company, location, provider, fit score, matched keywords, full description, and links to open or copy the posting URL.

### Analytics dashboard

The **Analytics** page summarizes portfolio metrics, Plotly charts (jobs by industry/location, company priority, career/job status breakdowns), top 20 opportunities by fit score, and the 30 most recent jobs.

### Search features

- **Global search** (sidebar): searches company names, industries, job titles, descriptions, and matched keywords
- **Keyword search** (Jobs page): filter jobs by terms like Python, machine learning, bioinformatics, neuroscience, fMRI, or healthcare

Selected company and job persist in the sidebar while navigating between pages.

### Planned AI features (Coming Soon)

Future phases will add:

- Resume tailoring for specific job postings
- Cover letter generation
- Outreach message generation
- Application tracking

These are visible as disabled placeholders in the UI and are not implemented yet.

## GitHub Exclusions

The following are **not** committed to GitHub:

- Raw scraped HTML (`data/raw/`)
- Cache files (`data/cache/`)
- Local SQLite databases (`*.db`, `*.sqlite`)
- Generated outputs (`outputs/*`)
- Environment files with API keys (`.env`, `.env.local`)
- Virtual environments (`venv/`, `.venv/`)

Only the scaffold, configuration templates, and seed company inventory are tracked in version control.

## Project Structure

```
job-search-agent/
├── AGENTS.md         # Agent workflow router (v2)
├── DATA_CONTRACT.md  # Schemas, file ownership, merge rules
├── docs/             # PRDs, ADRs (architecture decisions)
├── app/              # Streamlit dashboard entry point
├── config/           # settings.yaml, profile.yml, sources.yml, …
├── user/             # CV, career profile, proof points (human-owned)
├── skills/           # Agent SKILL.md workflows
├── data/             # company_inventory.csv, staging/, source_evidence/
├── reports/          # company_fit/, job_fit/ evaluation reports
├── outputs/          # Legacy CSV exports (fit scores, discovery previews)
├── prompts/          # Ollama prompt templates (legacy scorer)
├── src/
│   ├── schemas/      # Re-exports Pydantic models for agent JSON
│   ├── validators/   # Staging file validation helpers
│   ├── database/     # SQLite models and queries
│   ├── discovery/    # Directory scraping and inventory merge
│   ├── careers/      # Career page URL discovery
│   ├── jobs/         # Job extraction, filtering, CLI
│   ├── llm/          # Ollama fit scoring (Phase 1)
│   ├── ui/           # Streamlit dashboard
│   └── …
└── tests/
```
