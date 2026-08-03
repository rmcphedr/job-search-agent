---
name: company-fit-evaluation
description: Evaluate companies against the user profile. Output CompanyFitResult JSON to data/staging/ and optional markdown reports in reports/company_fit/.
---

# Company Fit Evaluation

Score how well each company matches the candidate profile.

## Read first

- [user/career_profile.md](../../user/career_profile.md)
- [user/proof_points.md](../../user/proof_points.md)
- [config/target_roles.yml](../../config/target_roles.yml)
- [config/scoring_weights.yml](../../config/scoring_weights.yml)
- [data/company_inventory.csv](../../data/company_inventory.csv) (read-only)
- Legacy prompt reference: [prompts/company_fit.md](../../prompts/company_fit.md)

## Your job

1. Load companies to evaluate (from inventory, event payload, or a filtered subset).
2. Research each company: website, careers page, mission, tech stack, funding stage if available.
3. Score against profile dimensions (see below).
4. Write **one JSON file per company** (event-driven) or batch staging file.
5. Optional per-company markdown report.

### Event-driven mode (Hermes)

When triggered by `company.merged` from the orchestrator:

- Evaluate **one company at a time** (serial).
- **Do not re-evaluate** if the company already exists in `data/company_evaluations.csv` unless the user explicitly requested re-evaluation.
- Write to `data/staging/runs/<run_id>/company_evaluations/<slug>.json` (single object, not array).
- Read [user/agent_calibration.md](../../user/agent_calibration.md) for learned preferences.
- Read calibration themes before scoring; apply user corrections from prior runs when reasoning.

## Scoring dimensions (0–10 each)

| Dimension | Weight hint |
|-----------|---------------|
| `industry_alignment` | AI, healthcare, biotech, neuroscience fit |
| `mission_alignment` | Scientific impact, healthcare innovation |
| `career_alignment` | Target roles likely available |
| `growth_potential` | Stage, funding, career trajectory |
| `fit_score` | Overall (weight mission + career heavily) |

Also provide: `reasoning`, `best_roles[]`, `interesting_factors[]`, `red_flags[]`, `confidence`.

## Output format

### Per-record (preferred)

`data/staging/runs/<run_id>/company_evaluations/<slug>.json` — single object:

```json
{
  "company_name": "Acme Health AI",
  "fit_score": 7.5,
  "industry_alignment": 8.0,
  "mission_alignment": 7.0,
  "career_alignment": 7.5,
  "growth_potential": 6.5,
  "reasoning": "Strong healthcare ML focus with research culture.",
  "best_roles": ["ML Scientist", "Research Scientist"],
  "interesting_factors": ["PyTorch stack", "imaging AI"],
  "red_flags": [],
  "confidence": 7.0
}
```

### Batch (legacy)

`data/staging/company_evaluations_<run_id>.json` — JSON array of objects with the same fields.

Schema: `CompanyFitResult`. Return **JSON only** in staging files.

Optional report: `reports/company_fit/<company_slug>_<timestamp>.md`

## Python merge

```bash
python -m src.validators.merge --file data/staging/runs/<run_id>/company_evaluations/<slug>.json
python -m src.orchestration.watch_staging   # auto-merge on write
python -m src.llm.score_companies --limit 5   # Ollama batch alternative
```

Validated results export to `data/company_evaluations.csv` (canonical) and `outputs/company_fit_scores.csv` (legacy).

## Rules

- Do not modify `data/company_inventory.csv`.
- Use evidence from `data/source_evidence/` when available.
- Flag low confidence when website/description is sparse.

## Next step

Prioritize companies above `config/profile.yml` → `min_company_fit_score` for **job_discovery_from_website**.
