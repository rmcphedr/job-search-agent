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
5. Write **one JSON file per company** under the run directory (preferred for event-driven merge).
6. Update run manifest counts as you stage each company.

## Output format (per-record — preferred)

Hermes runs use `data/staging/runs/<run_id>/`:

```
data/staging/runs/<run_id>/manifest.json
data/staging/runs/<run_id>/company_candidates/<slug>.json
```

Each `<slug>.json` is a **single** `CompanyCandidate` object:

```json
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
```

Initialize a run:

```bash
python -m src.validators.merge --init-run <run_id> --request '{"count":50}'
```

The staging watcher (`python -m src.orchestration.watch_staging`) merges each file automatically.

## Output format (batch — legacy)

Write `data/staging/company_candidates_<run_id>.json` as a JSON **array**. Merge via:

```bash
python -m src.validators.merge --file data/staging/company_candidates_<run_id>.json
```

Schema: `CompanyCandidate` in [src/schemas/README.md](../../src/schemas/README.md).

## Deterministic fallback (Python)

```bash
python -m src.discovery.run_directory_discovery --dry-run
python -m src.discovery.run_directory_discovery --source life_sciences_bc
python -m src.validators.merge --file data/staging/company_candidates_<run_id>.json
```

## Quality bar

- Prefer companies with external websites over directory-only pages.
- Boost confidence when industry matches profile (AI, healthcare, biotech, neuroscience).
- Record why each company was included in `notes`.

## Next step

Hermes orchestrator polls `company.merged` events and delegates to **company_fit_evaluation** (serial, one company at a time).
