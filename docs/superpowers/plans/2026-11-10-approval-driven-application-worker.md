# Approval-Driven Application Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every job the same Fully automate and Draft for review actions, backed by a resumable local worker that handles multi-page applications and human handoffs.

**Architecture:** Python owns run state and canonical data in SQLite; an isolated local browser handles portal navigation; Hermes drafts typed, evidence-backed answers in staging; the sibling resume pipeline produces documents. Streamlit starts and monitors runs but never hosts long-running work.

**Tech Stack:** Python, SQLite, Pydantic, Playwright, Streamlit, Hermes CLI, pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-approval-driven-application-worker-design.md`

## Global Constraints

- Both actions appear for every opportunity regardless of fit score; no automatic job enrollment.
- A Fully automate click authorizes final submission for that job only when every required value is confirmed or specifically approved and no human gate remains.
- Draft for review may advance non-final pages to reveal requirements but never presses final submit without another user action.
- Account creation, verification, MFA, CAPTCHA, consent, unsupported controls, and unsupported factual claims pause for handoff.
- Never infer a successful submission from a completed checklist or automatically retry an ambiguous final-submit attempt.
- Agents write drafts to staging; Python validates and merges canonical SQLite data. Reuse the sibling resume bridge.
- Preserve unrelated working-tree edits. Update ADR-019 by superseding it with a new ADR for the changed authorization model.

## Review Focus

- A second click or worker must not create or claim a duplicate active run (Task 1 test).
- An unsupported answer or stale profile must pause without filling an invented value (Task 2 test).
- A later page must be inspected anew; old fields cannot be assumed to describe it (Task 3 test).
- A resumed account handoff must re-inspect the current page and retain the authenticated session (Task 3 test).
- An ambiguous submit result must never be retried and must not mark Applied (Task 5 test).

---

## File map

- `src/database/application_runs.py`: enqueue, claim, transition, change mode, cancel, approve, and read durable runs.
- `src/database/migrate.py`, `src/database/schema.sql`: run, checkpoint, and answer-draft storage.
- `src/applications/answer_models.py`, `src/applications/answer_policy.py`: typed answer drafts and provenance/readiness rules.
- `src/applications/answer_agent.py`, `skills/application_answering/SKILL.md`: bounded Hermes invocation and staging output.
- `src/applications/browser_session.py`: isolated persistent browser, page observation, field actions, and handoff.
- `src/orchestration/application_worker.py`: one-run-at-a-time state machine and CLI.
- `src/applications/submission.py`: guarded final click and confirmation evidence.
- `src/database/application_submissions.py`: atomic confirmed-submission reconciliation.
- `src/ui/review_view.py`, `src/ui/tracking_view.py`, `src/ui/operations_view.py`: two actions, run progress, answer approval, browser handoff, review packet, and run metrics.
- `docs/adr/`, `DATA_CONTRACT.md`, `AGENTS.md`: record new authorization and storage contracts.

### Task 1: Durable application runs

**Files:** Create `src/database/application_runs.py`; modify `src/database/migrate.py`, `src/database/schema.sql`; test `tests/test_application_runs.py`.

**Interfaces:** Produce `enqueue_application(job_id: int, mode: str, *, connection=None) -> dict`, `claim_next_application(worker_id: str, lease_seconds: int = 900, *, connection=None) -> dict | None`, `transition_application(run_id: int, status: str, *, pause_reason: str | None = None, checkpoint: dict | None = None, connection=None) -> dict`, `set_application_mode(run_id: int, mode: str) -> dict`, `cancel_application(run_id: int) -> dict`, and `get_application_run(job_id: int) -> dict | None` (latest run). Modes are `fully_automate` and `draft_for_review`; terminal statuses are `submitted`, `failed`, and `cancelled` (with `submission_uncertain` nonclaimable).

- [ ] Write `test_enqueues_either_mode_once_and_rejects_duplicate_active_run`, `test_claim_is_exclusive_and_expired_lease_recovers`, `test_mode_change_requires_explicit_call_and_cancel_stops_claim`, and `test_migration_adds_runs_without_enrolling_historical_jobs` using temporary SQLite databases.
- [ ] Run `pytest tests/test_application_runs.py -q`; expect failures for missing API/schema.
- [ ] Add a run table with job FK, mode, status, lease, pause reason, JSON checkpoint, attempt marker, and timestamps; add indexes and the next migration version. Make enqueue atomic with tracking and preparation start; reject absent/expired jobs and duplicate active runs.
- [ ] Run `pytest tests/test_application_runs.py -q`; expect pass.
- [ ] Commit only Task 1 files.

### Task 2: Evidence-backed answers and document preparation

**Files:** Create `src/applications/answer_models.py`, `src/applications/answer_policy.py`, `src/applications/answer_agent.py`, `skills/application_answering/SKILL.md`; modify `src/database/application_runs.py`, `src/integrations/resume_pipeline.py` only if needed for the worker; test `tests/test_application_answers.py`.

**Interfaces:** Produce `AnswerDraft` with `field_key`, `answer`, `evidence_refs`, `approval_status`; `draft_answer(run_id: int, question: dict, evidence: dict) -> AnswerDraft`; `classify_answer(field: dict, evidence: dict) -> str` returning `confirmed`, `approval_required`, or `human_required`; `approve_answer(run_id: int, field_key: str, answer: str) -> dict`. Agent invocation uses a configurable executable and bounded `hermes --oneshot` call from the project root; the prompt points to `skills/application_answering/SKILL.md` and a per-run output path. Typed JSON is staged under `data/staging/application_runs/<run_id>/` and validated before SQLite changes.

- [ ] Write tests for confirmed contact/employment facts from candidate-owned profile files or explicit `application_facts`, missing/stale master profile, sensitive work-authorization/compensation/attestation fields, invalid agent JSON, and a drafted unknown question that cannot be filled until approved. Fake the Hermes executable; do not call a model in tests.
- [ ] Run `pytest tests/test_application_answers.py -q`; expect failures.
- [ ] Implement the Pydantic contract, provenance policy, agent bridge, staged output, and approval write path. Treat generated resume text as output rather than factual evidence. Use `src.profile.master_profile` staleness check.
- [ ] Run `pytest tests/test_application_answers.py -q`; expect pass.
- [ ] Commit only Task 2 files.

### Task 3: Multi-page browser and handoff

**Files:** Create `src/applications/browser_session.py`; modify `src/applications/generic_form.py`, `src/applications/dayforce.py`, `src/applications/inspection.py` as needed; test `tests/test_application_browser_session.py` with local HTML fixtures.

**Interfaces:** Produce `observe_page(page) -> PageObservation` (URL, page identity, fields, validation, gates, next/final action), `fill_observed_page(page, observation: PageObservation, values: dict[str, str]) -> FillOutcome`, `advance_nonfinal(page, observation: PageObservation) -> PageObservation`, and `open_application_browser(run_id: int) -> context manager`. The browser has a dedicated ignored local profile; one active run owns it. In `--watch` mode the worker keeps its headed browser open during a handoff, and the user acts in that window; resume always calls `observe_page` again. After process restart, reopen the profile and reconcile or replay non-final steps.

- [ ] Write fixture tests for a two-page form whose second-page fields differ, a dynamic file chooser, a provider validation message, account handoff followed by a changed page, a restarted profile that lost wizard state, and an unrecognized navigation control that pauses instead of clicking.
- [ ] Run `pytest tests/test_application_browser_session.py -q`; expect failures.
- [ ] Implement page observation and non-final navigation with Playwright label/role locators; separate final-submit identification from Next. Persist only minimal checkpoint metadata and exclude browser profiles/traces from Git.
- [ ] Run `pytest tests/test_application_browser_session.py -q`; expect pass.
- [ ] Commit only Task 3 files.

### Task 4: Local worker and review packet

**Files:** Create `src/orchestration/application_worker.py`; modify `src/database/application_runs.py`, `src/database/application_workspace.py`, `src/database/application_preparation.py`; test `tests/test_application_worker.py`.

**Interfaces:** Produce `process_application_run(run_id: int, *, browser_factory, answer_agent, resume_bridge) -> dict` and CLI `python -m src.orchestration.application_worker --once` / `--watch`. `get_review_packet(run_id: int) -> dict` reads durable state and artifact paths. `resume_application(run_id: int) -> dict` releases a user pause into the queue without losing the checkpoint.

- [ ] Write tests with fake browser/agent/bridge for an inactive or unverified posting, document generation once, conditional cover-letter generation, later-page question drafting, pause/resume, invalid artifact paths, and a draft-for-review run stopping at `ready_for_review`.
- [ ] Run `pytest tests/test_application_worker.py -q`; expect failures.
- [ ] Implement the bounded state machine; write each transition before external actions and keep Streamlit out of the worker process. Record field outcomes through Python CRUD and expose review-packet data.
- [ ] Run `pytest tests/test_application_worker.py -q`; expect pass.
- [ ] Commit only Task 4 files.

### Task 5: Guarded submission and reconciliation

**Files:** Create `src/applications/submission.py`; modify `src/database/application_submissions.py`, `src/database/application_runs.py`, `src/database/application_automation.py`; test `tests/test_application_submission_worker.py` and extend `tests/test_application_submissions.py`.

**Interfaces:** Produce `submit_if_authorized(run_id: int, page, observation: PageObservation) -> SubmissionOutcome` and `record_confirmed_application_submission(run_id: int, receipt: dict, *, connection=None) -> dict`. A durable attempt marker is written before the final click; receipt evidence is required before the atomic Applied transition.

- [ ] Write tests for both modes, missing/unapproved required answers, unresolved gates, a single confirmed click, ambiguous result with no retry/Applied transition, and an already submitted run returning the existing immutable snapshot.
- [ ] Run `pytest tests/test_application_submission_worker.py tests/test_application_submissions.py -q`; expect failures.
- [ ] Implement readiness and mode checks, attempt marker, confirmation inspection, `submission_uncertain`, and atomic snapshot/stage transition. Preserve the existing manual reconciliation path.
- [ ] Run `pytest tests/test_application_submission_worker.py tests/test_application_submissions.py -q`; expect pass.
- [ ] Commit only Task 5 files.

### Task 6: Dashboard integration and architecture docs

**Files:** Modify `src/ui/review_view.py`, `src/ui/tracking_view.py`, `src/ui/operations_view.py`, `DATA_CONTRACT.md`, `AGENTS.md`, `docs/adr/ADR-019-human-reviewed-application-agent.md`, `docs/adr/README.md`; create the next available `docs/adr/ADR-023-approval-driven-application-worker.md` (verify numbering before writing); test `tests/test_application_workflow_ui.py`.

**Interfaces:** Review inbox actions call `enqueue_application`. Tracking view shows mode/status, handoff reason, answer drafts and approval controls, and the packet. UI actions call `approve_answer`, `set_application_mode`, `cancel_application`, and `resume_application`, never browser work in the Streamlit process. Operations shows counts and elapsed time by status/provider.

- [ ] Write UI tests proving both actions appear on every eligible opportunity independent of fit score, mode is stored and can be explicitly changed or cancelled, a paused unknown answer can be edited/approved/resumed, a draft packet stops before submission, an uncertain submission is prominently shown without a retry button, and operations metrics reflect completed and paused runs.
- [ ] Run `pytest tests/test_application_workflow_ui.py -q`; expect failures.
- [ ] Implement the UI and retire the direct synchronous submit path. Supersede ADR-019, document the new canonical/staging fields and worker CLI, and preserve existing unrelated edits when updating docs.
- [ ] Run `pytest tests/test_application_workflow_ui.py tests/test_application_runs.py tests/test_application_answers.py tests/test_application_browser_session.py tests/test_application_worker.py tests/test_application_submission_worker.py tests/test_application_submissions.py -q`; expect pass.
- [ ] Run `pytest -q`; investigate only concrete failures from the change.
- [ ] Commit only Task 6 files, then review the branch diff against the spec.
