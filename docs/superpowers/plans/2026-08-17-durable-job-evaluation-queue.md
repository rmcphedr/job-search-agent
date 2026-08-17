# Durable Job Evaluation Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably evaluate every eligible new job with a budget-aware Codex worker and expose queue, model, token, and failure telemetry in Streamlit.

**Architecture:** Python owns a transactional SQLite queue and telemetry tables. Codex claims compact batches and submits typed `JobFitResult` payloads through a synchronous Python validation-and-commit service; it never issues arbitrary SQL. Discovery and description lifecycle hooks keep queue eligibility synchronized, while a new Operations dashboard reads repository APIs.

**Tech Stack:** Python 3, SQLite, Pydantic, PyYAML, Streamlit, pandas, pytest

## Global Constraints

- Read `DATA_CONTRACT.md` before changing canonical data behavior.
- Agents perform fit judgment; Python validates, deduplicates, stores, and logs.
- Default worker policy is `gpt-5.6-terra` with `low` reasoning.
- Escalation uses `gpt-5.6-terra` with `medium` reasoning only for configured uncertainty or validation failures.
- Exact token usage must be labelled `measured`; tokenizer-derived usage must be labelled `estimated`; otherwise use `unavailable`.
- Stop before claiming work that would exceed a run's configured job or estimated-token ceiling.
- Never enroll historical jobs during migration, application startup, or worker startup.
- Historical backlog enrollment requires preview, bounded selection, projected usage, and explicit user confirmation; enrollment never starts a worker.
- Ollama remains legacy/manual and is not an automatic evaluation path.
- Preserve the unrelated local modification to `data/company_inventory.csv`.

---

### Task 1: Queue and telemetry schema

**Files:**
- Modify: `src/database/migrate.py`
- Modify: `src/database/schema.sql`
- Create: `tests/test_job_evaluation_queue.py`

**Interfaces:**
- Produces SQLite tables `job_evaluation_queue`, `job_evaluation_runs`, and `job_evaluation_attempts`.
- Produces migration version 11 for all later tasks.

- [ ] **Step 1: Write failing migration tests**

Create a temporary database with the base `companies` and `job_postings` tables, call `apply_migrations`, and assert:

```python
tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert {"job_evaluation_queue", "job_evaluation_runs", "job_evaluation_attempts"} <= tables

connection.execute("INSERT INTO job_evaluation_queue (job_id, status) VALUES (1, 'queued')")
with pytest.raises(sqlite3.IntegrityError):
    connection.execute("INSERT INTO job_evaluation_queue (job_id, status) VALUES (1, 'queued')")
```

Also assert invalid status and usage-provenance values fail `CHECK` constraints.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `pytest tests/test_job_evaluation_queue.py -v`

Expected: FAIL because the three tables do not exist.

- [ ] **Step 3: Add migration 11 and canonical DDL**

Define:

```sql
CREATE TABLE job_evaluation_queue (
  queue_id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('queued','deferred','claimed','completed','failed','cancelled')),
  priority INTEGER NOT NULL DEFAULT 100,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 2,
  requested_model TEXT NOT NULL DEFAULT 'gpt-5.6-terra',
  requested_reasoning_effort TEXT NOT NULL DEFAULT 'low',
  defer_reason TEXT,
  lease_owner TEXT,
  lease_expires_at TEXT,
  last_error TEXT,
  eligible_at TEXT,
  claimed_at TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(job_id) REFERENCES job_postings(job_id)
);
```

Add `job_evaluation_runs` with `run_id`, status, trigger, model/reasoning policy, job/token limits, timestamps, aggregate counts/tokens, and usage provenance. Add `job_evaluation_attempts` with run/queue/job identity, model, reasoning effort, status, timestamps, duration, input/output tokens, provenance, escalation reason, validation outcome, and error. Add indexes for queue status/priority, lease expiry, run start time, and attempts by run/job.

- [ ] **Step 4: Run migration tests**

Run: `pytest tests/test_job_evaluation_queue.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/database/migrate.py src/database/schema.sql tests/test_job_evaluation_queue.py
git commit -m "feat: add job evaluation queue schema"
```

### Task 2: Transactional queue repository

**Files:**
- Create: `src/orchestration/job_evaluation_queue.py`
- Modify: `tests/test_job_evaluation_queue.py`

**Interfaces:**
- Produces `QueueItem`, `enqueue_job`, `sync_job_eligibility`, `claim_batch`, `release_stale_claims`, `complete_job`, `fail_job`, `retry_job`, `cancel_job`, and `queue_summary`.
- `claim_batch(*, run_id: str, worker_id: str, limit: int, lease_seconds: int, connection=None) -> list[QueueItem]` must claim atomically.

- [ ] **Step 1: Write failing repository tests**

Cover these exact behaviors:

```python
first = enqueue_job(1, description_ready=False, connection=connection)
assert first.status == "deferred"
assert enqueue_job(1, description_ready=True, connection=connection).status == "queued"
assert connection.execute("SELECT count(*) FROM job_evaluation_queue").fetchone()[0] == 1

claimed = claim_batch(run_id="run-1", worker_id="worker-a", limit=1, lease_seconds=300, connection=connection)
assert [item.job_id for item in claimed] == [1]
assert claim_batch(run_id="run-2", worker_id="worker-b", limit=1, lease_seconds=300, connection=connection) == []
```

Also test priority ordering, completion idempotency, bounded retry to `failed`, cancellation, and recovery of an expired lease.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_job_evaluation_queue.py -v`

Expected: FAIL importing `src.orchestration.job_evaluation_queue`.

- [ ] **Step 3: Implement the repository**

Use `BEGIN IMMEDIATE` for claims. Select queued rows ordered by `priority ASC, eligible_at ASC, queue_id ASC`, update the selected IDs to `claimed`, assign the lease and increment `attempt_count`, then return typed dataclasses. All public mutation functions accept an optional connection so discovery/merge callers can include transitions in their own transaction.

`enqueue_job` must upsert by `job_id`, preserve completed work unless explicitly reactivated, clear stale lease/error fields on reactivation, and select `queued` versus `deferred` from `description_ready`.

- [ ] **Step 4: Run queue tests**

Run: `pytest tests/test_job_evaluation_queue.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orchestration/job_evaluation_queue.py tests/test_job_evaluation_queue.py
git commit -m "feat: add transactional evaluation queue"
```

### Task 3: Wire job and description lifecycle transitions

**Files:**
- Modify: `src/jobs/save_jobs.py`
- Modify: `src/jobs/description_enrichment.py`
- Modify: `tests/test_description_enrichment.py`
- Create: `tests/test_job_evaluation_lifecycle.py`

**Interfaces:**
- Consumes `enqueue_job`, `sync_job_eligibility`, and `cancel_job` from Task 2.
- Produces automatic queue transitions for insert, rediscovery, enrichment, description change, and expiration.

- [ ] **Step 1: Write failing lifecycle tests**

Assert that saving a new job creates exactly one queue row. A verified description produces `queued`; no verified description produces `deferred`. Assert rediscovery without material description change does not reactivate a completed item.

Extend description tests to assert:

```python
assert queue_status(connection, job_id) == "queued"  # after successful enrichment
assert job_row["fit_score"] is None                  # changed description invalidates score
assert queue_status(connection, job_id) == "cancelled"  # authoritative expiration
```

- [ ] **Step 2: Run lifecycle tests and verify failure**

Run: `pytest tests/test_job_evaluation_lifecycle.py tests/test_description_enrichment.py -v`

Expected: FAIL because producers do not update the queue.

- [ ] **Step 3: Add lifecycle hooks in existing transactions**

After inserting `job_postings`, read `lastrowid` and call `enqueue_job` with readiness defined as `description_status == 'enriched' and description_checked_at is not null`. When rediscovery adds a previously missing description, clear stale evaluation and call `sync_job_eligibility(..., reactivate=True)`.

In description enrichment, promote verified active jobs to queued. When authoritative content changes after evaluation, clear the evaluation and reactivate the queue item. When expiration sets `active = 0`, cancel pending or claimed queue work with reason `job_expired`.

- [ ] **Step 4: Run lifecycle and regression tests**

Run: `pytest tests/test_job_evaluation_lifecycle.py tests/test_description_enrichment.py tests/test_board_discovery.py tests/test_employer_ats_sources.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobs/save_jobs.py src/jobs/description_enrichment.py tests/test_job_evaluation_lifecycle.py tests/test_description_enrichment.py
git commit -m "feat: enqueue jobs across description lifecycle"
```

### Task 4: Run budgets, usage estimation, and claim packets

**Files:**
- Create: `config/agent_evaluation.yaml`
- Create: `src/orchestration/evaluation_policy.py`
- Create: `src/orchestration/evaluation_worker.py`
- Create: `tests/test_evaluation_worker.py`

**Interfaces:**
- Produces `EvaluationPolicy`, `UsageEstimate`, `EvaluationPacket`, `start_run`, `estimate_job_tokens`, and `claim_evaluation_packet`.
- `claim_evaluation_packet(run_id: str, worker_id: str, *, connection=None) -> EvaluationPacket | None` stops before exceeding configured limits.

- [ ] **Step 1: Write failing policy and budget tests**

Test loading these defaults:

```yaml
default_model: gpt-5.6-terra
normal_reasoning_effort: low
escalation_reasoning_effort: medium
confidence_threshold: 6.0
batch_size: 5
lease_seconds: 900
max_attempts: 2
max_jobs_per_run: 25
estimated_token_limit: 200000
```

Assert a run with 19,500 consumed tokens and a projected 1,000-token next job stops under a 20,000 limit only when the estimate would exceed—not equal—the ceiling. Assert the packet includes profile text once and exact job identity/description records.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_evaluation_worker.py -v`

Expected: FAIL because the policy and worker modules do not exist.

- [ ] **Step 3: Implement configuration, estimation, and packet claiming**

Load YAML with Pydantic validation. Estimate tokens with a deterministic character fallback of `ceil(len(text) / 4)` and label it `estimated`; accept runtime-provided counts as `measured`. Build shared profile context from the files already required by `skills/job_fit_evaluation/SKILL.md`.

Before claiming, compute remaining job/token capacity. Select only the largest leading subset that fits both limits. If none fits, mark the run `budget_exhausted` and return `None` without claiming. Store the projection and provenance on the run.

- [ ] **Step 4: Run worker tests**

Run: `pytest tests/test_evaluation_worker.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/agent_evaluation.yaml src/orchestration/evaluation_policy.py src/orchestration/evaluation_worker.py tests/test_evaluation_worker.py
git commit -m "feat: add budget-aware evaluation worker"
```

### Task 5: Synchronous validated submission and escalation

**Files:**
- Modify: `src/orchestration/handlers.py`
- Create: `src/orchestration/evaluation_submission.py`
- Create: `src/orchestration/evaluation_cli.py`
- Modify: `skills/job_fit_evaluation/SKILL.md`
- Modify: `tests/test_staging_merge.py`
- Modify: `tests/test_evaluation_worker.py`

**Interfaces:**
- Consumes queue completion APIs and `JobFitResult` validation.
- Produces `submit_job_evaluations(run_id: str, queue_ids: list[int], payload: list[dict], usage: UsageRecord, *, connection=None) -> SubmissionResult`.
- Produces CLI actions `backlog-preview`, `backlog-enroll`, `claim`, `submit`, `fail`, `retry`, and `status`.

- [ ] **Step 1: Write failing atomic-submission tests**

Assert that a valid payload updates `job_postings.fit_score`, `fit_reason`, `fit_details`, and `evaluated_at`, completes the queue item, and records one successful attempt in the same transaction. Assert an identity mismatch rolls back all three effects. Assert confidence below `6.0` returns `needs_escalation=True` and keeps the item claimed for a medium-reasoning retry.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_staging_merge.py tests/test_evaluation_worker.py -v`

Expected: FAIL because synchronous submission and queue completion are not connected.

- [ ] **Step 3: Extract connection-aware validation and implement submission**

Refactor the existing job merge validation into a helper that accepts validated `JobFitResult` records and an existing connection. Keep the file-based handler as a compatibility wrapper. In `submit_job_evaluations`, verify every queue ID belongs to the supplied job result, validate current title/company/active state/description timestamp, and update job, queue, run, and attempt rows atomically.

Retain submitted JSON under `data/staging/runs/<run_id>/job_evaluations/` using a deterministic batch filename after successful validation. Do not require the agent to manage that file.

- [ ] **Step 4: Add CLI and skill instructions**

The CLI prints JSON so an agent can call:

```bash
python3 -m src.orchestration.evaluation_cli claim --run-id "$RUN_ID" --worker-id codex
python3 -m src.orchestration.evaluation_cli submit --run-id "$RUN_ID" --queue-ids 1,2 --file /tmp/job-results.json --model gpt-5.6-terra --reasoning low
```

`backlog-preview` is read-only. `backlog-enroll` requires explicit job IDs from
a prior preview plus `--confirm`; it must reject an unbounded request. Neither
command starts a worker.

Update the skill to use the claim/submit boundary, default to Terra/low, and retry only flagged jobs with Terra/medium.

- [ ] **Step 5: Run submission and CLI tests**

Run: `pytest tests/test_staging_merge.py tests/test_evaluation_worker.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/orchestration/handlers.py src/orchestration/evaluation_submission.py src/orchestration/evaluation_cli.py skills/job_fit_evaluation/SKILL.md tests/test_staging_merge.py tests/test_evaluation_worker.py
git commit -m "feat: submit agent evaluations transactionally"
```

### Task 6: Operations data service and dashboard

**Files:**
- Create: `src/ui/operations_data.py`
- Create: `src/ui/operations_view.py`
- Modify: `app/dashboard.py`
- Create: `tests/test_operations_data.py`

**Interfaces:**
- Consumes queue/run/attempt tables from Tasks 1–5.
- Produces `load_queue_metrics`, `load_recent_evaluation_runs`, `load_model_efficiency`, `load_problem_items`, `preview_backlog`, `enroll_backlog`, and `render_operations_view`.

- [ ] **Step 1: Write failing aggregation tests**

Seed mixed queue states and attempts, then assert:

```python
metrics = load_queue_metrics(connection=connection)
assert metrics.ready == 2
assert metrics.deferred == 1
assert metrics.stale == 1
assert metrics.projected_tokens > 0

efficiency = load_model_efficiency(connection=connection)
assert efficiency.iloc[0]["model"] == "gpt-5.6-terra"
assert efficiency.iloc[0]["usage_provenance"] in {"measured", "estimated", "mixed", "unavailable"}
```

Test retry/defer/cancel UI actions through repository functions, not raw SQL.
Test that backlog preview is read-only, newest-first, and filterable by verified
description, source, company, and minimum keyword score. Test that enrollment
rejects missing confirmation, an empty selection, and projected usage above the
user-selected ceiling.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_operations_data.py -v`

Expected: FAIL importing `src.ui.operations_data`.

- [ ] **Step 3: Implement the read service**

Return dataclasses for headline metrics and pandas DataFrames for run/model/problem tables. Calculate stale claims from `lease_expires_at`, rolling tokens per completed job from successful attempts, and backlog projection from measured rolling averages with deterministic estimates as fallback.

- [ ] **Step 4: Build and register the Streamlit view**

Add `"Operations": render_operations_view` to `PAGES`. Render queue metric cards, budget projection, recent runs, per-model efficiency, failed/deferred drill-down, and guarded retry/defer/cancel buttons. Display `measured`, `estimated`, or `unavailable` beside every usage/cost value.

Add a separate **Historical backlog** panel. Default to newest jobs with verified
descriptions, allow source/company/minimum-keyword-score filters and row
selection, require maximum jobs and an estimated-token ceiling, show the
projection, and require an explicit confirmation checkbox before enabling
**Enroll selected jobs**. Enrollment must not launch evaluation. Show a copyable
`evaluation_cli` command for the separately initiated capped run rather than
trying to launch Codex.

- [ ] **Step 5: Run UI data and dashboard import tests**

Run: `pytest tests/test_operations_data.py tests/test_analytics_view.py tests/test_board_health.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ui/operations_data.py src/ui/operations_view.py app/dashboard.py tests/test_operations_data.py
git commit -m "feat: add evaluation operations dashboard"
```

### Task 7: Backlog enrollment, end-to-end verification, and documentation

**Files:**
- Modify: `tests/test_pipeline_integration.py`
- Modify: `DATA_CONTRACT.md`
- Modify: `AGENTS.md`
- Modify: `docs/adr/ADR-020-durable-agent-job-evaluation-queue.md`
- Modify: `docs/adr/README.md`

**Interfaces:**
- Consumes all earlier task interfaces.
- Produces a documented, migration-safe rollout and accepted ADR.

- [ ] **Step 1: Add the failing end-to-end integration test**

Exercise: save a job with verified description → assert queued → start capped run → claim packet → submit valid `JobFitResult` → assert canonical score, completed queue item, successful attempt, and completed run aggregates. Add a second job whose projected tokens exceed the remaining budget and assert it remains queued.

- [ ] **Step 2: Run the integration test and verify failure before final wiring**

Run: `pytest tests/test_pipeline_integration.py -v`

Expected: FAIL until all lifecycle and telemetry integrations are complete.

- [ ] **Step 3: Complete integration wiring and documentation**

Document the three new canonical SQLite tables in `DATA_CONTRACT.md`. Update the MVP workflow and commands in `AGENTS.md` to use `evaluation_cli backlog-preview/backlog-enroll/claim/submit`; label `src.llm.score_jobs` legacy/manual. State explicitly that migration and startup never enroll the historical backlog. Change ADR-020 status from `Proposed` to `Accepted` and update its index status after implementation passes.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
pytest tests/test_job_evaluation_queue.py tests/test_job_evaluation_lifecycle.py tests/test_evaluation_worker.py tests/test_operations_data.py tests/test_staging_merge.py tests/test_pipeline_integration.py -v
pytest -q
python3 -m src.orchestration.evaluation_cli status
```

Expected: all tests PASS; status prints valid JSON without mutating queue state.

- [ ] **Step 5: Perform a safe read-only backlog preview**

Run:

```bash
python3 -m src.orchestration.evaluation_cli backlog-preview --limit 10 --verified-only
```

Expected: prints counts for eligible, deferred, already evaluated, and inactive
jobs without database writes. Do not run `backlog-enroll` until the user reviews
the preview and explicitly chooses the bounded subset.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pipeline_integration.py DATA_CONTRACT.md AGENTS.md docs/adr/ADR-020-durable-agent-job-evaluation-queue.md docs/adr/README.md
git commit -m "docs: finalize durable job evaluation workflow"
```
