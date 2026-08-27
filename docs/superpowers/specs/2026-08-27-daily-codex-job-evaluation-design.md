# Daily Codex Job Evaluation Design

**Date:** 2026-08-27
**Status:** Approved for planning

## Goal

Extend the existing daily Codex opportunity scan so its best newly discovered
jobs receive canonical fit evaluations before the run finishes. The evaluated
jobs must be available in the Streamlit application without using Ollama or the
OpenAI API.

## Constraints

- Run through the existing Codex scheduled task authenticated with the user's
  ChatGPT/Codex account. Do not use `OPENAI_API_KEY` or call the OpenAI API.
- Preserve the agentic-v2 boundary: the agent produces typed evaluation
  results; Python validates and writes canonical SQLite fields.
- Process only jobs inserted or materially description-enriched by the current
  daily scan. Never consume the historical unevaluated backlog automatically.
- Evaluate three qualifying jobs by default and at most five in one run.
- Skip jobs that already have a current evaluation.
- Use the existing durable queue, leases, run records, attempts, and validated
  submission interface.

## Architecture

The existing standalone Codex scheduled task remains the sole daily
orchestrator. It runs in the local project checkout so it can access the user
profile, staging artifacts, SQLite database, and report directory.

Discovery continues to stage `JobCandidate` records and merge them through
`save_jobs`. The merge layer enrolls eligible new or materially enriched jobs
in `job_evaluation_queue`; enrollment does not itself start evaluation.

After discovery and merge, the same Codex run selects and claims a bounded
subset of current-run queue items. The agent evaluates each claimed job using
the `job-fit-evaluation` skill and submits `JobFitResult` objects through the
existing Python submission interface. Python performs schema validation,
identity checks, staging/audit persistence, canonical SQLite updates, and queue
completion.

No continuously running worker, separate OS cron process, or API-backed model
client is introduced.

## Selection Policy

Candidates must satisfy all of the following:

1. The job was inserted or materially description-enriched in the current
   discovery run.
2. The job is active, pending evaluation, and has a sufficiently complete,
   verified description.
3. The job does not already have a current canonical evaluation.
4. The job is not excluded by durable candidate preferences, such as an
   explicitly unwanted employment type.

The agent reuses the daily scan's combined fit judgment to order qualifying
jobs. It evaluates the top three qualifying jobs. It may expand to four or five
only when the additional jobs are credible runners-up worth reviewing; it must
not fill the batch with weak candidates merely to reach five.

Selection is restricted by `discovery_run_id` and an explicit job-ID list at
the claim boundary. Queue priority alone must not allow older jobs into the
daily batch.

## Model and Usage Policy

The scheduled task uses Codex with ChatGPT sign-in, so runs draw from the
user's Codex plan usage rather than API token billing. The task must not read or
use an API key.

Routine daily evaluation uses `gpt-5.6-luna` with low reasoning effort. The
hard limit is five jobs per scheduled run. The durable run record retains an
estimated token ceiling and stops claiming further work before that ceiling.
If exact Codex token telemetry is unavailable, usage remains explicitly marked
as estimated or unavailable rather than presented as measured.

The initial token ceiling is 30,000 estimated tokens for the complete
evaluation batch. Discovery and browser work are still subject to the Codex
scheduled task's overall plan usage and may not expose exact token counts to
the repository.

## Data Flow

1. The scheduled task creates one UTC scan run ID.
2. Gmail and LinkedIn discovery produce staging and evidence artifacts.
3. Python validates and merges job candidates with that `discovery_run_id`.
4. The agent determines the top three to five qualifying current-run job IDs.
5. Python creates a bounded evaluation run and claims only those IDs.
6. The agent writes typed evaluation JSON in `data/staging/`.
7. Python validates and merges each result, updates the queue, and records the
   attempt and run telemetry.
8. The daily report lists selected, completed, skipped, and failed evaluation
   counts and links to the evaluated jobs in the application where practical.

## Failure Handling

- A discovery failure must not cause historical queue work to be claimed.
- If fewer than three jobs qualify, evaluate only those that qualify.
- Validation failures remain retryable and are reported; they do not trigger
  unbounded retries in the same scheduled run.
- A lease or submission failure leaves the durable item recoverable according
  to existing queue retry behavior.
- Reaching the five-job or estimated-token limit ends evaluation cleanly;
  remaining current-run items stay queued for explicit future handling.
- A job that lacks reliable description evidence remains deferred rather than
  being scored from an invented or incomplete description.

## Observability

The existing Operations dashboard remains the source of queue and run
telemetry. Each scheduled run records its trigger, requested model and
reasoning effort, job cap, estimated-token ceiling, attempted/completed counts,
duration where available, token provenance, and last error.

The daily report adds an evaluation summary distinguishing discovery ranking
from canonical completed evaluation. Missing runtime token telemetry must not
leave ambiguous blank fields: the UI should label the value as unavailable or
estimated based on stored provenance.

## Scheduled Task Update

Update the existing automation named `Daily opportunity scan: Gmail +
LinkedIn`; do not create a second automation. Preserve its daily 7:00 AM local
schedule and project target. Revise its durable prompt to invoke the
`job-fit-evaluation` skill and the current-run bounded queue workflow after
merge. Change the scheduled model to `gpt-5.6-luna` with low reasoning effort.

Because the task runs in the local checkout, the computer must be powered on,
the ChatGPT desktop app must be running, and the project must remain available
at the configured path.

## Verification

- Unit-test current-run selection, the default-three/hard-five behavior,
  previously evaluated jobs, insufficient qualifying jobs, and historical
  backlog exclusion.
- Test token-cap stopping and validation-failure recovery.
- Test that the report and Operations queries distinguish estimated,
  unavailable, and measured telemetry.
- Run the scheduled prompt manually against a controlled scan result before
  relying on unattended execution.
- Confirm the automation retains the intended project, local execution mode,
  cadence, model, reasoning effort, and active status after update.

## Non-goals

- Automatically evaluating the historical backlog.
- Allowing agents to write canonical SQLite evaluation fields directly.
- Using Ollama as the primary evaluator.
- Calling the OpenAI API or estimating API dollar charges for Codex plan usage.
- Adding a continuously running worker or dashboard-launched Codex runtime.
