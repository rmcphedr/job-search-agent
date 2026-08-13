---
name: job-discovery-from-website
description: Discover job postings from company career pages. Output JobCandidate JSON to data/staging/. Python merges into SQLite.
---

# Job Discovery from Website

Extract open roles from career pages listed in company inventory.

## Read first

- [DATA_CONTRACT.md](../../DATA_CONTRACT.md)
- [data/company_inventory.csv](../../data/company_inventory.csv) — `career_page` column
- [config/target_roles.yml](../../config/target_roles.yml)
- [config/job_keywords.yaml](../../config/job_keywords.yaml)
- [config/job_discovery.yaml](../../config/job_discovery.yaml)

## Your job

1. Select companies with valid `career_page` URLs (skip empty / `NOT FOUND`).
2. Navigate career pages and ATS systems (Greenhouse, Lever, Ashby, Workday, etc.).
3. Extract job title, URL, location, description snippet, provider if detectable.
4. Pre-filter by target roles and keywords from config.
5. Write staging JSON; store page evidence in `data/source_evidence/<run_id>/`.

## Output format

`data/staging/job_candidates_<run_id>.json`:

```json
[
  {
    "company_name": "Acme Health AI",
    "title": "Machine Learning Scientist",
    "location": "Montreal, QC",
    "url": "https://boards.greenhouse.io/acme/jobs/123",
    "description": "Optional full or summary text",
    "provider": "greenhouse",
    "source_career_page": "https://acmehealth.ai/careers",
    "keyword_score": 0.5,
    "matched_keywords": ["machine learning", "python"]
  }
]
```

Schema: `JobCandidate`.

## Python pipeline (deterministic)

Career page discovery:

```bash
python -m src.careers.update_inventory_career_pages --limit 50
```

Job extraction + deduped SQLite insert:

```bash
python -m src.jobs.run_job_discovery --limit 50
python -m src.jobs.run_job_discovery --company "Valence Labs" --dry-run
```

Registered employer ATS sources:

```bash
# Discover employer ATS boards, refresh them, and label legacy ATS jobs
python -m src.jobs.run_employer_ats_discovery

# Preview one provider or employer without source/job writes
python -m src.jobs.run_employer_ats_discovery --provider greenhouse --dry-run
python -m src.jobs.run_employer_ats_discovery --company "Valence Labs" --dry-run
```

Key modules: `src/jobs/job_extractors`, `src/jobs/filter_jobs`, `src/jobs/save_jobs`.

## Agent vs Python

- **Agent:** useful for JS-heavy sites, ambiguous navigation, or companies where Python extractors fail.
- **Python:** preferred for known ATS patterns and batch runs.

Always stage agent results; never insert into SQLite directly.

## Next step

Run **job_fit_evaluation** on staged or SQLite-active jobs.
