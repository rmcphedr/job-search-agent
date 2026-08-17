# Schemas

Pydantic models for agent staging JSON and Python merge pipelines. Import from `src.schemas` or the source modules below.

## Discovery

| Model | Module | Staging use |
|-------|--------|-------------|
| `CompanyCandidate` | `src.discovery.models` | `data/staging/company_candidates_*.json` |
| `DirectorySource` | `src.discovery.models` | Config validation |

## Jobs

| Model | Module | Staging use |
|-------|--------|-------------|
| `JobCandidate` | `src.jobs.job_models` | `data/staging/job_candidates_*.json` |

## Evaluation

| Model | Module | Staging use |
|-------|--------|-------------|
| `CompanyFitResult` | `src.llm.schemas` | `data/staging/company_evaluations_*.json` |
| `JobFitResult` | `src.llm.schemas` | `data/staging/job_evaluations_*.json` |
| `JobTriageResult` | `src.llm.schemas` | Pre-screen triage (Python job pipeline) |

## Validate staging JSON

```python
import json
from pathlib import Path

from src.schemas import CompanyCandidate

raw = json.loads(Path("data/staging/company_candidates_run.json").read_text())
records = [CompanyCandidate.model_validate(row) for row in raw]
```

Future: batch-validate and merge via `python -m src.validators.merge` and `python -m src.orchestration.watch_staging`.

## CSV columns

See [DATA_CONTRACT.md](../../DATA_CONTRACT.md) for `company_inventory.csv` and evaluation export columns.
