# ADR-023: OpenRouter batch fit scoring

**Status:** Accepted
**Date:** 2026-11-11
**Deciders:** Project maintainer
**Supersedes:** None
**Superseded by:** None

## Context

Routine job-fit scoring needs a prompt, the candidate profile, and a job description. The agent evaluation queue remains the path for an explicit review session, and it does not start a model by itself. The batch scorer already builds that prompt and validates `JobFitResult`, but it could only call local Ollama and it wrote a CSV instead of the SQLite columns the dashboard reads.

Hosted calls have to stay bounded. Most newly discovered jobs are listing cards, and a free model should only see postings with a real description.

## Decision

- Configure the batch scorer in `config/llm.yaml`. The default provider is OpenRouter, model `nvidia/nemotron-3.5-lightning:free`. `google/gemma-4-31b-it:free` is the preferred instruction model when Google's shared free pool is accepting requests.
- Read the API key from `OPENROUTER_API_KEY` in the gitignored project `.env`. The process does not override a key already present in the environment.
- `python -m src.llm.score_jobs --since-days 2` scores active jobs found in that window whose description is at least `min_description_chars` (200). A hosted run must pass `--since-days`, `--limit`, or `--company`.
- Write `fit_score`, `fit_reason`, `fit_details`, and `evaluated_at` on `job_postings`. Close an unclaimed evaluation-queue row for that job so the agent queue does not score it again.
- Keep Ollama available by setting `provider: ollama`.
- Do not send title-only triage or description cleanup to the hosted provider. Those steps stay local or deterministic.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Agent queue for every new job | Stronger judgment | Manual, capped at a handful of jobs, and it never starts itself |
| Ollama only | No API key | Too slow for a routine pass, and scores never reached the dashboard |
| **OpenRouter free model for bounded batch scoring** | Uses the existing prompt and shows scores in the dashboard | Free-tier rate limits; listing cards still need a description first |

## Consequences

### Positive

- Jobs with a real description can be scored without an agent session.
- The dashboard reads the same fit columns as an agent merge.
- An unbounded hosted run is refused.

### Negative / trade-offs

- Free-model quality and rate limits vary.
- Jobs without a description stay unscored until a later enrichment pass.

### Follow-ups

- Run description fetch and a second keyword filter before the model, then call this scorer on the survivors.
- Compare a sample of free-model scores with an agent review before widening the batch.

## Implementation notes

- Client: `src/llm/llm_client.py`
- Command: `src/llm/score_jobs.py`
- Config: `config/llm.yaml`
- Secret: `.env` (`OPENROUTER_API_KEY`)

## Related

- ADRs: ADR-006, ADR-013, ADR-020
- Code: `src/llm/score_jobs.py`, `prompts/job_fit.md`
