---
name: job-fit-evaluation
description: Score job postings against the user profile. Output JobFitResult JSON to data/staging/ and optional reports in reports/job_fit/.
---

# Job Fit Evaluation

Evaluate how well each job posting matches the candidate.

## Read first

- [user/master_cv.md](../../user/master_cv.md) — generated canonical profile copy; never edit manually
- [user/career_profile.md](../../user/career_profile.md)
- [user/proof_points.md](../../user/proof_points.md)
- [user/project_inventory.md](../../user/project_inventory.md)
- [user/agent_calibration.md](../../user/agent_calibration.md)
- [config/target_roles.yml](../../config/target_roles.yml)
- Active jobs: SQLite `job_postings` or staging from discovery
- Legacy prompt: [prompts/job_fit.md](../../prompts/job_fit.md)

## Your job

1. Load job records (title, company, location, description).
2. Compare required/preferred skills to profile and proof points.
3. Score fit, list skill matches/gaps, concerns, recommended actions.
4. Write staging JSON and optional markdown report.

Before scoring, run `python3 -m src.profile.master_profile --check`. If stale, warn and synchronize. Classify every material requirement as **confirmed evidence**, **transferable evidence**, **active development area**, **genuine gap**, or **unverified claim**. Unverified claims must not affect scoring, and active development areas must not be presented as established experience.

Apply durable preference themes from `user/agent_calibration.md`, including employment-type exclusions, experience-equivalency rules, location weighting, and strategic-growth tolerance.

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
    "job_id": 123,
    "job_title": "Machine Learning Scientist",
    "company_name": "Acme Health AI",
    "fit_score": 8.0,
    "salary": null,
    "seniority": "Mid-level",
    "employment_type": "Full-time",
    "role_summary": ["Build and validate healthcare ML systems"],
    "job_requirements": ["Graduate degree", "2+ years relevant experience"],
    "preferred_qualifications": ["Healthcare ML experience"],
    "qualification_assessment": [
      {"requirement": "Graduate degree", "status": "match", "evidence": "Confirmed PhD", "preferred": false},
      {"requirement": "Healthcare ML experience", "status": "gap", "evidence": "No direct industry evidence", "preferred": true}
    ],
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

Include `job_id` for SQLite-backed jobs. The deterministic merger verifies it against the job title and company before updating the database.

Optional: `reports/job_fit/<job_slug>_<timestamp>.md`

## Python merge

### Durable agent queue (primary)

Preview and explicitly enroll historical jobs; never enroll them automatically:

```bash
python3 -m src.orchestration.evaluation_cli backlog-preview --limit 10 --verified-only
python3 -m src.orchestration.evaluation_cli backlog-enroll --job-ids 1,2 --max-jobs 10 --token-limit 50000 --confirm
```

Claiming is a separate action. Use `gpt-5.6-terra` with low reasoning for the
packet and submit structured results synchronously. Retry only validation-failed
or confidence-below-threshold jobs with medium reasoning.

```bash
python3 -m src.validators.merge --file data/staging/job_evaluations_<run_id>.json
python -m src.llm.score_jobs --limit 10
python -m src.llm.score_jobs --company "Valence Labs"
```

Export: `outputs/job_fit_scores.csv` (→ `data/job_evaluations.csv`).

## Next step

**ranking** skill / Python shortlist generation.
