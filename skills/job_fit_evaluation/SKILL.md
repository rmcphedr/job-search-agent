---
name: job-fit-evaluation
description: Score job postings against the user profile. Output JobFitResult JSON to data/staging/ and optional reports in reports/job_fit/.
---

# Job Fit Evaluation

Evaluate how well each job posting matches the candidate.

## Read first

- [user/career_profile.md](../../user/career_profile.md)
- [user/proof_points.md](../../user/proof_points.md)
- [user/project_inventory.md](../../user/project_inventory.md)
- [config/target_roles.yml](../../config/target_roles.yml)
- Active jobs: SQLite `job_postings` or staging from discovery
- Legacy prompt: [prompts/job_fit.md](../../prompts/job_fit.md)

## Your job

1. Load job records (title, company, location, description).
2. Compare required/preferred skills to profile and proof points.
3. Score fit, list skill matches/gaps, concerns, recommended actions.
4. Write staging JSON and optional markdown report.

## Internal dimensions (inform `fit_score`)

- Skill match
- Experience / seniority match
- Career alignment with target roles
- Growth opportunity

## Output format

`data/staging/job_evaluations_<run_id>.json`:

```json
[
  {
    "job_title": "Machine Learning Scientist",
    "company_name": "Acme Health AI",
    "fit_score": 8.0,
    "skills_match": ["Python", "PyTorch", "healthcare ML"],
    "skill_gaps": ["clinical trial design"],
    "recommended_actions": ["Emphasize Mila multimodal work"],
    "why_fit": "Strong overlap with ML + healthcare research background.",
    "concerns": [],
    "confidence": 7.5
  }
]
```

Schema: `JobFitResult`. JSON only in staging files.

Optional: `reports/job_fit/<job_slug>_<timestamp>.md`

## Python merge

```bash
python -m src.llm.score_jobs --limit 10
python -m src.llm.score_jobs --company "Valence Labs"
```

Export: `outputs/job_fit_scores.csv` (→ `data/job_evaluations.csv`).

## Next step

**ranking** skill / Python shortlist generation.
