# Durable Job Evaluation Queue and Observability Design

## Problem

Job discovery writes active postings to SQLite with `fit_score` and
`evaluated_at` unset, but no durable mechanism assigns each eligible posting to
an agent evaluator. The legacy Ollama scorer is slow, batch-oriented, and writes
a CSV export rather than driving the canonical SQLite evaluation workflow. Jobs
found outside an active agent session can therefore remain unevaluated without
a visible failure or backlog.

The system also lacks operational visibility into evaluation status, model
selection, retries, throughput, and token consumption. Codex does not always
expose exact token usage to project code, so usage reporting must distinguish
measurements from estimates.

## Goals

- Durably enqueue every new or materially refreshed active job.
- Evaluate eligible jobs with an agent and merge results through the existing
  validated staging boundary.
- Use `gpt-5.6-terra` with low reasoning for normal evaluation and medium
  reasoning only for uncertain or invalid results.
- Bound each run by configurable job and estimated-token limits without losing
  work.
- Expose queue health, run history, model use, throughput, retries, and token or
  cost estimates in the existing Streamlit dashboard.
- Backfill the current unevaluated-job backlog safely and idempotently.

## Non-goals

- Making Ollama the primary or automatic evaluator.
- Allowing agents to write canonical SQLite evaluation fields directly.
- Starting or controlling Codex agents from the Streamlit process.
- Treating estimated tokens or subscription quota as exact API billing.
- Building a general-purpose workflow engine for unrelated project tasks.

## Architecture

### Durable queue

Add a canonical SQLite `job_evaluation_queue` table with one current queue item
per `job_id`. Python owns all queue mutations. The record contains:

- `queue_id`, `job_id`, `status`, and `priority`
- `attempt_count`, `max_attempts`, and `last_error`
- `requested_model` and `requested_reasoning_effort`
- lease owner and lease-expiration fields for atomic claims
- eligibility/defer reason
- created, eligible, claimed, completed, and updated timestamps

Supported states are `queued`, `deferred`, `claimed`, `completed`, `failed`, and
`cancelled`. A unique constraint on `job_id` prevents duplicate current work.
Material description changes reactivate the existing queue item and clear the
stale evaluation rather than inserting a second item.

`save_jobs` enqueues newly inserted active jobs. A job with a current verified
description becomes `queued`; a job without one becomes `deferred`. Description
enrichment promotes deferred jobs to queued. Authoritative expiration cancels
pending work. A one-time CLI backfills active jobs whose `evaluated_at` is null.

### Agent worker boundary

Provide a Python CLI that atomically claims an eligible batch under a renewable,
time-limited lease and emits a compact evaluation packet. The packet contains
the shared candidate profile once and the claimed job records, including exact
`job_id`, title, company, location, and verified description.

The Codex orchestration skill consumes the packet, evaluates the batch, and
writes `JobFitResult` JSON to `data/staging/`. The existing deterministic merger
validates job identity and description currency before updating SQLite. A
successful merge marks the matching queue item completed. Agents never update
the queue or canonical job row directly.

Normal evaluation uses `gpt-5.6-terra` with low reasoning. A result escalates
individually to medium reasoning only when output validation fails, confidence
is below the configured threshold, or material requirements remain ambiguous.
The initial batch size is five and remains configurable.

### Budget behavior

Each worker run accepts maximum jobs and an estimated-token ceiling. Before
claiming the next batch, it projects the batch cost using rolling observed usage
when available and tokenizer estimates otherwise. Reaching the ceiling stops the
run before another claim; remaining items stay queued for the next session.

The worker does not silently switch to a different model. Model selection is an
explicit policy recorded on the run and queue attempt. A cheaper fallback model
may be added later through configuration.

Planning estimates for five-job batches are:

- 8,000–15,000 shared profile/instruction input tokens per batch
- 2,000–5,000 input tokens per job description and metadata
- 500–1,000 output tokens per completed job
- approximately 4,000–8,000 amortized input tokens and 500–1,000 output tokens
  per completed job
- approximately 200,000–400,000 input and 25,000–50,000 output tokens for fifty
  jobs

These figures are estimates, not quota guarantees. The design targets a medium-
reasoning escalation rate below 15 percent and makes the actual rate visible.

## Telemetry Model

Add SQLite run and attempt records rather than overloading the existing generic
`runs.notes` JSON. An evaluation run records status, trigger, model policy,
reasoning policy, limits, timestamps, jobs attempted/completed, and aggregate
usage. Each attempt records queue/job/run identity, model, reasoning effort,
duration, retry or escalation reason, validation outcome, and usage.

Every token field carries a provenance value:

- `measured`: supplied by the model or runtime
- `estimated`: calculated with the configured tokenizer
- `unavailable`: no trustworthy value exists

Dollar estimates are derived from a configurable model-rate catalog and are
shown only when rates exist. Codex subscription or quota usage is displayed as
token/capacity information, not misrepresented as API spend.

## Dashboard

Add an **Operations** page to the existing Streamlit dashboard with:

- queue counters for ready, deferred, claimed, failed, stale, and completed work
- oldest-item age and stale-lease warnings
- projected tokens for the ready backlog and the next configured run
- recent runs with model, reasoning effort, duration, throughput, retries,
  escalation rate, and measured/estimated usage
- per-model efficiency: tokens and seconds per completed job, validation-failure
  rate, and estimated cost where configured
- drill-down tables for failed/deferred items and their reasons
- manual retry, defer, and cancel controls implemented through Python queue APIs
- a copyable command or agent instruction for starting the next evaluation run

The dashboard reports state and manages deterministic queue controls. It does
not attempt to launch a Codex agent from the Streamlit process.

## Data Flow

1. Job discovery inserts or materially refreshes a posting.
2. Python creates, reactivates, defers, or cancels its unique queue item.
3. Enrichment promotes jobs with verified descriptions to `queued`.
4. A worker claims a budget-safe batch using a lease.
5. Codex evaluates with Terra/low and stages structured JSON.
6. Low-confidence or invalid items retry individually with Terra/medium.
7. The existing merge handler validates and writes canonical evaluation fields.
8. Merge completion finalizes the queue item and attempt telemetry.
9. Unclaimed jobs remain durable for a later agent session.

## Failure and Recovery

- Expired leases return claimed items to the ready pool without duplicating
  completed work.
- Schema-invalid output retries once according to policy; repeated failure marks
  the item failed with a reviewable error.
- A changed verified description invalidates an older evaluation and requeues
  the job.
- An inactive or authoritatively expired job cancels pending evaluation.
- Queue claiming, completion, and retry transitions are transactional and
  idempotent.
- Merge identity or description-currency failures do not partially update a
  batch and remain visible in attempt telemetry.

## Configuration

Add an agent-evaluation configuration section covering:

- default model: `gpt-5.6-terra`
- normal reasoning effort: `low`
- escalation reasoning effort: `medium`
- confidence threshold and escalation conditions
- batch size, lease duration, maximum attempts, and retry backoff
- default maximum jobs and estimated tokens per run
- optional model input/output rates and tokenizer identifiers

Model policy belongs to agent orchestration configuration, not the legacy
`config/llm.yaml` Ollama settings.

## Testing

Unit tests cover queue insertion, uniqueness, refresh reactivation, description-
based deferral and promotion, expiration cancellation, atomic claims, stale lease
recovery, retry limits, and budget stopping. Telemetry tests cover measured,
estimated, and unavailable usage plus model-rate calculations.

Worker tests cover batch packet construction, low-to-medium escalation rules,
and idempotent completion. Dashboard tests cover aggregate queue/run metrics and
manual transition APIs. An integration test exercises discovery → queue → claim
→ staged `JobFitResult` → validated merge → completed queue item.

## Rollout

1. Add queue, run, and attempt schemas plus deterministic repository APIs.
2. Wire discovery, enrichment, expiration, and evaluation merge transitions.
3. Add backlog and worker CLIs and update the agent evaluation skill.
4. Add token estimation, model-rate configuration, and the Operations page.
5. Backfill active unevaluated jobs and run a small capped evaluation batch.
