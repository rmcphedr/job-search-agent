---
name: ranking
description: Produce a ranked shortlist from company and job evaluations using config/scoring_weights.yml. Python performs final aggregation.
---

# Ranking

Combine company fit and job fit scores into a prioritized shortlist.

## Read first

- [config/scoring_weights.yml](../../config/scoring_weights.yml)
- [DATA_CONTRACT.md](../../DATA_CONTRACT.md)
- Evaluation inputs:
  - `outputs/company_fit_scores.csv` or `data/staging/company_evaluations_*.json`
  - `outputs/job_fit_scores.csv` or `data/staging/job_evaluations_*.json`
  - SQLite `job_postings` for active jobs

## Your job (agent assist)

1. Join job evaluations with company evaluations on `company_name`.
2. Apply weights from `scoring_weights.yml`:
   - `shortlist.company_weight` (default 0.35)
   - `shortlist.job_weight` (default 0.65)
3. Compute `combined_score = company_weight * company_fit + job_weight * job_fit`.
4. Filter below `shortlist.min_combined_score`.
5. Rank descending; output staging summary JSON.

## Output format

`data/staging/shortlist_<run_id>.json`:

```json
[
  {
    "rank": 1,
    "company_name": "Acme Health AI",
    "job_title": "Machine Learning Scientist",
    "job_url": "https://...",
    "company_fit_score": 7.5,
    "job_fit_score": 8.0,
    "combined_score": 7.8,
    "rationale": "Top ML + healthcare alignment"
  }
]
```

## Python responsibilities (deterministic)

- Validate score ranges (0–10)
- Deduplicate by `job_url`
- Write final CSV export (future: `outputs/shortlist.csv`)
- Log run in SQLite `runs` table

Existing dashboard analytics (`src/ui/analytics_view.py`) reads fit score CSVs today.

## MVP note

No dedicated ranking CLI yet — agent produces staging shortlist; human or dashboard reviews. Future: `python -m src.orchestration.rank`.
