# Daily Codex Job Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing daily Codex opportunity scan canonically evaluate its top three qualifying current-run jobs, optionally up to five, without API billing or historical-backlog consumption.

**Architecture:** Extend the durable queue with an exact-job claim boundary and expose a `daily-claim` CLI that validates every requested job against one `discovery_run_id`, a five-job hard cap, and a 30,000-token ceiling. The existing Codex scheduled task will select the worthwhile current-run job IDs, claim them through that CLI, apply the existing job-fit skill, and submit typed results through the existing Python canonicalization boundary.

**Tech Stack:** Python 3, SQLite, argparse, Pydantic, pytest, Streamlit, Codex scheduled tasks.

**Spec:** `docs/superpowers/specs/2026-08-27-daily-codex-job-evaluation-design.md`

## Global Constraints

- Use ChatGPT/Codex sign-in only; do not read `OPENAI_API_KEY` or call the OpenAI API.
- Agents stage typed `JobFitResult` data; Python alone writes canonical SQLite fields.
- Only jobs inserted or materially description-enriched in the current daily scan are eligible.
- Evaluate three qualifying jobs by default and never more than five per run.
- Never claim historical backlog jobs implicitly.
- Routine scheduled evaluation uses `gpt-5.6-luna`, low reasoning, and a 30,000 estimated-token ceiling.
- Preserve the user's unrelated `data/company_inventory.csv` worktree change.

---

### Task 1: Preserve current-run provenance for description enrichment

**Files:**
- Modify: `src/jobs/save_jobs.py`
- Test: `tests/test_job_evaluation_lifecycle.py`

**Interfaces:**
- Consumes: `SaveJobsOptions.discovery_run_id: str | None` and the existing duplicate-description enrichment branch.
- Produces: an enriched existing `job_postings` row whose `discovery_run_id` is updated to the current scan ID and whose queue item is reactivated.

- [ ] **Step 1: Write the failing enrichment provenance test**

Add a test that saves an existing description-less job, rediscovers it with a verified description and `SaveJobsOptions(pending_evaluation=True, discovery_run_id="daily-1")`, then asserts:

```python
row = connection.execute(
    "SELECT discovery_run_id, description_status FROM job_postings WHERE title='Rediscovered'"
).fetchone()
assert tuple(row) == ("daily-1", "enriched")
assert connection.execute(
    "SELECT status FROM job_evaluation_queue q JOIN job_postings j USING(job_id) "
    "WHERE j.title='Rediscovered'"
).fetchone()[0] == "queued"
```

- [ ] **Step 2: Run the test and verify the missing provenance failure**

Run: `venv/bin/python -m pytest tests/test_job_evaluation_lifecycle.py -v`

Expected: FAIL because the enrichment update leaves `discovery_run_id` unchanged.

- [ ] **Step 3: Update provenance in the enrichment merge**

Add this assignment to the existing description-enrichment `UPDATE` and pass the option value as a bound parameter:

```sql
discovery_run_id = coalesce(?, discovery_run_id),
```

Keep the existing `sync_job_eligibility(..., reactivate=True)` call so a materially enriched job becomes eligible again.

- [ ] **Step 4: Run the lifecycle tests**

Run: `venv/bin/python -m pytest tests/test_job_evaluation_lifecycle.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the provenance fix**

```bash
git add src/jobs/save_jobs.py tests/test_job_evaluation_lifecycle.py
git commit -m "Track discovery run for enriched jobs"
```

### Task 2: Add exact-job queue claims and bounded daily packets

**Files:**
- Modify: `src/orchestration/job_evaluation_queue.py`
- Modify: `src/orchestration/evaluation_worker.py`
- Test: `tests/test_job_evaluation_queue.py`
- Test: `tests/test_evaluation_worker.py`

**Interfaces:**
- Produces: `claim_jobs(*, job_ids: list[int], worker_id: str, lease_seconds: int, connection=None) -> list[QueueItem]`.
- Extends: `claim_evaluation_packet(run_id: str, worker_id: str, *, policy: EvaluationPolicy | None = None, profile_text: str = "", job_ids: list[int] | None = None, discovery_run_id: str | None = None, connection=None) -> EvaluationPacket | None`.
- Enforces: when `job_ids` or `discovery_run_id` is supplied, only the intersection of those current-run jobs may be returned or claimed.

- [ ] **Step 1: Write failing exact-claim tests**

Create three queued jobs where jobs 1 and 2 have `discovery_run_id='daily-1'` and job 3 has `discovery_run_id='old-run'`. Add assertions equivalent to:

```python
claimed = claim_jobs(
    job_ids=[2], worker_id="daily", lease_seconds=300, connection=connection
)
assert [item.job_id for item in claimed] == [2]
assert connection.execute(
    "SELECT status FROM job_evaluation_queue WHERE job_id=1"
).fetchone()[0] == "queued"
```

Add a worker test:

```python
packet = claim_evaluation_packet(
    "daily-eval-1",
    "codex-scheduled",
    policy=EvaluationPolicy(default_model="gpt-5.6-luna", batch_size=5,
                            max_jobs_per_run=5, estimated_token_limit=30_000),
    job_ids=[2, 3],
    discovery_run_id="daily-1",
    connection=connection,
)
assert [job.job_id for job in packet.jobs] == [2]
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `venv/bin/python -m pytest tests/test_job_evaluation_queue.py tests/test_evaluation_worker.py -v`

Expected: FAIL because `claim_jobs` and filtered packet arguments do not exist.

- [ ] **Step 3: Implement transactional exact-job claiming**

Implement `claim_jobs` using `BEGIN IMMEDIATE` for owned connections, an
`UPDATE ... WHERE job_id IN (...) AND status='queued'`, and a final `SELECT`.
Reject an empty `job_ids` list by returning `[]`; deduplicate IDs while
preserving caller order. Do not alter `claim_batch`, which remains the manual
backlog worker path.

- [ ] **Step 4: Filter and budget the packet before claiming**

Extend the candidate query in `claim_evaluation_packet` with bound predicates
for `j.job_id IN (...)` and `j.discovery_run_id=?`. Preserve caller job order,
drop non-ready/evaluated jobs, estimate profile plus description tokens, and
call `claim_jobs` with exactly the selected IDs. Raise `ValueError` if a
filtered daily claim is requested without both a non-empty job list and a
discovery run ID.

Use the existing run's `max_jobs` and `estimated_token_limit`; never silently
fall back to the generic queue when the filtered set becomes empty.

- [ ] **Step 5: Run focused tests**

Run: `venv/bin/python -m pytest tests/test_job_evaluation_queue.py tests/test_evaluation_worker.py -v`

Expected: PASS, including proof that the old-run item remains queued.

- [ ] **Step 6: Commit exact current-run claims**

```bash
git add src/orchestration/job_evaluation_queue.py src/orchestration/evaluation_worker.py tests/test_job_evaluation_queue.py tests/test_evaluation_worker.py
git commit -m "Add bounded current-run evaluation claims"
```

### Task 3: Add the scheduled-task CLI contract

**Files:**
- Modify: `src/orchestration/evaluation_cli.py`
- Create: `tests/test_evaluation_cli.py`
- Modify: `skills/job_fit_evaluation/SKILL.md`

**Interfaces:**
- Produces command: `python3 -m src.orchestration.evaluation_cli daily-claim --run-id <evaluation-run-id> --discovery-run-id <scan-run-id> --job-ids 1,2,3 --worker-id codex-scheduled`.
- Produces JSON: an `EvaluationPacket` with only selected current-run jobs.
- Defaults: `model='gpt-5.6-luna'`, `reasoning='low'`, `max_jobs=5`, `token_limit=30000`, `trigger='scheduled_daily'`.

- [ ] **Step 1: Write failing CLI parser and execution tests**

Test the parser defaults:

```python
args = parser().parse_args([
    "daily-claim", "--run-id", "eval-1", "--discovery-run-id", "scan-1",
    "--job-ids", "1,2,3", "--worker-id", "codex-scheduled",
])
assert (args.model, args.reasoning, args.max_jobs, args.token_limit) == (
    "gpt-5.6-luna", "low", 5, 30_000
)
```

Also test that six IDs raise a parser or `ValueError`, duplicated IDs are
deduplicated, and the command passes `trigger='scheduled_daily'` plus the exact
IDs and discovery run ID to the worker boundary. Use monkeypatches for
`start_run` and `claim_evaluation_packet`; do not access the real database.

- [ ] **Step 2: Run the CLI tests and verify failure**

Run: `venv/bin/python -m pytest tests/test_evaluation_cli.py -v`

Expected: FAIL because `daily-claim` is not registered.

- [ ] **Step 3: Implement `daily-claim`**

Register the arguments above. Construct a per-run policy without mutating the
manual defaults:

```python
base = load_evaluation_policy()
policy = base.model_copy(update={
    "default_model": args.model,
    "normal_reasoning_effort": args.reasoning,
    "max_jobs_per_run": args.max_jobs,
    "batch_size": min(args.max_jobs, 5),
    "estimated_token_limit": args.token_limit,
})
```

Validate `1 <= len(unique_job_ids) <= min(args.max_jobs, 5)`, call
`start_run(..., trigger="scheduled_daily")`, then call
`claim_evaluation_packet(..., job_ids=unique_job_ids,
discovery_run_id=args.discovery_run_id)`. Serialize the packet with the
existing `asdict` pattern.

- [ ] **Step 4: Document the exact daily claim-and-submit workflow**

Add a “Scheduled daily batch” section to `skills/job_fit_evaluation/SKILL.md`
that requires current-scan IDs, shows the `daily-claim` command, requires
staging JSON, and shows the existing `submit` command with Luna/low. State that
the agent must submit only the returned `queue_id` values and must not replace
an empty packet with a generic claim.

- [ ] **Step 5: Run CLI and worker tests**

Run: `venv/bin/python -m pytest tests/test_evaluation_cli.py tests/test_evaluation_worker.py tests/test_job_evaluation_queue.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the scheduled CLI contract**

```bash
git add src/orchestration/evaluation_cli.py tests/test_evaluation_cli.py skills/job_fit_evaluation/SKILL.md
git commit -m "Add scheduled daily evaluation command"
```

### Task 4: Make unavailable efficiency telemetry explicit

**Files:**
- Modify: `src/ui/operations_data.py`
- Test: `tests/test_operations_data.py`

**Interfaces:**
- Extends: `load_model_efficiency(*, connection=None) -> pd.DataFrame`.
- Produces columns: `model`, `reasoning_effort`, `attempts`, `completed`, `avg_duration_ms`, `input_tokens`, `output_tokens`, `usage_provenance`.
- Display contract: unavailable duration/token aggregates are the string `Unavailable`; estimated aggregates remain numeric and are labeled `estimated`.

- [ ] **Step 1: Write the failing telemetry-label test**

Insert one completed attempt with null duration/tokens and
`usage_provenance='unavailable'`, then assert:

```python
row = load_model_efficiency(connection=connection).iloc[0]
assert row["avg_duration_ms"] == "Unavailable"
assert row["input_tokens"] == "Unavailable"
assert row["output_tokens"] == "Unavailable"
assert row["usage_provenance"] == "unavailable"
```

Add a second test with estimated token values and assert that numeric totals
remain numeric and provenance is `estimated`.

- [ ] **Step 2: Run the operations tests and verify failure**

Run: `venv/bin/python -m pytest tests/test_operations_data.py -v`

Expected: FAIL because the query returns null aggregates and omits provenance.

- [ ] **Step 3: Aggregate provenance and normalize unavailable values**

Update the SQL to aggregate provenance as `measured`, `estimated`,
`unavailable`, or `mixed`. After loading the frame, replace null display values
in `avg_duration_ms`, `input_tokens`, and `output_tokens` with `Unavailable`
only for unavailable data; do not turn real zeroes into unavailable values.

- [ ] **Step 4: Run operations tests**

Run: `venv/bin/python -m pytest tests/test_operations_data.py -v`

Expected: PASS.

- [ ] **Step 5: Commit telemetry clarity**

```bash
git add src/ui/operations_data.py tests/test_operations_data.py
git commit -m "Label unavailable evaluation telemetry"
```

### Task 5: Update and verify the existing Codex scheduled task

**Files:**
- Modify externally through Codex scheduled-task management: `daily-gmail-job-alert-import`
- Verify read-only mirror: `/Users/rmcph/.codex/automations/daily-gmail-job-alert-import/automation.toml`

**Interfaces:**
- Consumes: the `daily-claim` and `submit` CLI commands and `$job-fit-evaluation` skill.
- Produces: one active local scheduled task at 7:00 AM using `gpt-5.6-luna`, low reasoning, and the existing project ID.

- [ ] **Step 1: Run the full local regression suite before changing automation state**

Run: `venv/bin/python -m pytest -q`

Expected: PASS.

- [ ] **Step 2: Update the existing automation, not a duplicate**

Use scheduled-task management with ID `daily-gmail-job-alert-import`. Preserve
its name, active status, daily 7:00 AM schedule, local execution environment,
project ID `6f46e26d-86ef-4bb6-8eec-6c7269180676`, and project path. Set model to
`gpt-5.6-luna` and reasoning effort to `low`.

Append durable prompt requirements that:

- retain the scan's selected top three and up to two credible runners-up as an
  explicit ordered job-ID list;
- invoke `$job-fit-evaluation` after merge;
- call `daily-claim` with the scan run ID and only that ordered list;
- evaluate and submit only jobs returned in the packet;
- stop after five jobs or 30,000 estimated tokens;
- never use a generic claim when the daily packet is empty;
- never use Ollama, an API key, or the historical backlog;
- report selected, completed, skipped, failed, and remaining-current-run counts.

- [ ] **Step 3: View the stored automation and verify every preserved field**

Use scheduled-task management in view mode and confirm:

```text
id: daily-gmail-job-alert-import
status: ACTIVE
schedule: daily at 07:00 local time
execution_environment: local
model: gpt-5.6-luna
reasoning_effort: low
project_id: 6f46e26d-86ef-4bb6-8eec-6c7269180676
```

Confirm the prompt contains `daily-claim`, `$job-fit-evaluation`, the five-job
cap, 30,000-token ceiling, current-run restriction, and API/Ollama prohibition.

- [ ] **Step 4: Run a non-model CLI smoke test**

Run: `venv/bin/python -m src.orchestration.evaluation_cli --help`

Expected: output lists `daily-claim`; do not trigger a live discovery or model
run as part of this smoke test.

- [ ] **Step 5: Commit any final repository documentation adjustments**

If verification required repository documentation corrections, commit only
those explicit files. Do not add `data/job_search.db`, staging artifacts,
reports, `.env`, or `data/company_inventory.csv`.

### Task 6: Final verification and handoff

**Files:**
- Verify: all files changed by Tasks 1–5

**Interfaces:**
- Consumes: completed implementation and updated automation.
- Produces: evidence that the feature is safe for the next unattended daily run.

- [ ] **Step 1: Run targeted feature tests**

Run: `venv/bin/python -m pytest tests/test_job_evaluation_lifecycle.py tests/test_job_evaluation_queue.py tests/test_evaluation_worker.py tests/test_evaluation_cli.py tests/test_operations_data.py -v`

Expected: PASS.

- [ ] **Step 2: Run the complete test suite**

Run: `venv/bin/python -m pytest -q`

Expected: PASS with no baseline failures.

- [ ] **Step 3: Check repository hygiene**

Run: `git status --short` and `git diff --check`.

Expected: no unintended database, staging, report, secret, or cache changes;
the pre-existing `data/company_inventory.csv` modification remains uncommitted
and unchanged.

- [ ] **Step 4: Report operational expectations**

Handoff must state that the next scheduled run will evaluate three qualifying
current-run jobs and may evaluate up to five credible runners-up, consumes
Codex plan usage rather than API billing, and requires the computer and desktop
app to be running with the local project available.
