# Job Search Agent

A Python-based job-search intelligence agent for discovering, tracking, and scoring opportunities at AI, healthcare, neuroscience, and biotech companies.

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
├── config/           # settings.yaml, scoring.yaml
├── data/             # company_inventory.csv, raw/, cache/
├── outputs/          # generated reports and exports
├── prompts/          # LLM prompt templates (planned)
├── src/
│   ├── database/     # SQLite models and queries
│   ├── discovery/    # Directory source scraping and inventory updates
│   ├── scraping/     # HTTP fetching and parsing
│   ├── enrichment/   # LLM-based enrichment
│   ├── scoring/      # Fit scoring logic
│   ├── jobs/         # Job orchestration and CLI
│   └── utils/        # Shared helpers
└── tests/
```
