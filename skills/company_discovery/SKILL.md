---
name: company-discovery
description: Discover candidate companies from directory sources or web research. Output structured CompanyCandidate JSON to data/staging/. Use when expanding the company inventory.
---

# Company Discovery

Find companies aligned with the candidate's target industries and locations.

## Read first

- [AGENTS.md](../../AGENTS.md)
- [DATA_CONTRACT.md](../../DATA_CONTRACT.md)
- [config/sources.yml](../../config/sources.yml) → [config/directory_sources.yaml](../../config/directory_sources.yaml)
- [config/profile.yml](../../config/profile.yml) and [user/career_profile.md](../../user/career_profile.md)

## Your job

1. Identify companies from configured directory sources **or** targeted web research (biotech hubs, AI health startups, neuroscience employers).
2. For each company, collect: name, website (prefer external domain over directory profile URL), source metadata, confidence.
3. Skip duplicates already in [data/company_inventory.csv](../../data/company_inventory.csv) (match by domain or fuzzy name).
4. Save evidence under `data/source_evidence/<run_id>/`.
5. Write staging output — **do not edit canonical CSV**.

## Output format

Write `data/staging/company_candidates_<run_id>.json`:

```json
[
  {
    "company_name": "Acme Health AI",
    "website": "https://acmehealth.ai",
    "source_id": "manual_research",
    "source_name": "Web search — Montreal AI health",
    "source_url": "https://example.com/listing",
    "source_category": "AI healthcare startup",
    "confidence": 0.7,
    "notes": "Series A, ML imaging product"
  }
]
```

Schema: `CompanyCandidate` in [src/schemas/README.md](../../src/schemas/README.md).

Optional CSV with same columns for human review.

## Deterministic fallback (Python)

The existing scraper can run directory sources without an agent:

```bash
python -m src.discovery.run_directory_discovery --dry-run
python -m src.discovery.run_directory_discovery --source life_sciences_bc
```

Merge logic: `src.discovery.update_inventory` + `src.discovery.deduplicate`.

## Quality bar

- Prefer companies with external websites over directory-only pages.
- Boost confidence when industry matches profile (AI, healthcare, biotech, neuroscience).
- Record why each company was included in `notes`.

## Next step

Hand off to **company_fit_evaluation** skill, then Python merge if new candidates were staged.
