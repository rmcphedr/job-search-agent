# Approval-Driven Application Worker Design

**Status:** Draft for user review
**Date:** 2026-11-10

## Intent

Reduce the context switching between job review, resume tailoring, document folders, employer forms, and dashboard updates. Every reviewed opportunity offers the same two choices: **Fully automate** or **Draft for review**. Fit score may inform the user's choice but never hides or changes either option.

The user expects to spend more time on high-value applications and less time on approved medium-fit jobs. An approval applies to one job and one application run; it is not a standing authorization to apply to other jobs.

## Goals

- A single action starts a durable, inspectable application run from an existing job posting.
- The worker discovers requirements page by page, creates the needed documents through the existing resume pipeline, and drafts answers grounded in confirmed profile facts and job evidence.
- Fully automate proceeds to submission when the run stays within its approved rules. It pauses for account creation, email verification, MFA, CAPTCHA, consent, an unfamiliar answer, or an unsupported control. The worker drafts its best answer to an unfamiliar question for user approval and resumes afterward.
- Draft for review produces an editable packet of documents, answers, requirements, and unresolved items. It never presses final submit without a later explicit user action.
- The dashboard changes a job to Applied only after verified employer confirmation or an explicit user reconciliation of a submission completed outside the worker.

## Non-goals and anti-goals

- No bulk application approval or automatic enrollment based only on fit score.
- No invented qualifications, work authorization, salary expectations, personal disclosures, or other factual answers.
- No CAPTCHA solving, MFA bypass, silent account creation, or password storage in SQLite.
- No blind retry of a final-submit action after an ambiguous result.
- No replacement of the sibling resume-generation pipeline or direct agent writes to canonical SQLite tables.

## Existing constraints and reusable parts

- `DATA_CONTRACT.md` assigns canonical job and application data to Python and agent drafts to staging.
- `job_reviews`, `tracked_jobs`, `application_preparation_steps`, `application_sessions`, `application_fields`, `application_facts`, `application_audit_events`, and `application_submissions` already exist.
- The dashboard has a Quick Review inbox and application workspace. The resume and cover-letter bridges return artifacts from `../resume-generation-pipeline`.
- The current generic browser handler covers one page and opens a fresh browser context for submission. Dayforce inspection identifies only the first page. These handlers cannot serve as the unattended multi-page worker unchanged.
- ADR-019 currently requires a separate final confirmation. Fully automate changes that decision and requires an ADR update before implementation.

## Approaches

| Approach | Benefits | Costs |
|---|---|---|
| **Local background worker with durable SQLite runs (recommended)** | Reuses local documents, database, and browser; supports visible handoff and restart recovery | Computer must be awake during active browser work |
| Streamlit request handler performs the run | Smallest initial wiring change | Long synchronous waits, rerun interruption, and weak recovery make multi-page handoffs unreliable |
| Hosted worker and cloud browser | Can operate while the computer is off | Requires remote storage and protection of profile data, document artifacts, login sessions, and interactive handoff |

The proposed design uses the local worker. Model reasoning may be remote; browser control, durable state, and documents remain local.

## User experience and authorization

Each opportunity presents two equal actions:

1. **Fully automate.** The click records job-specific authorization to navigate non-final pages, transmit required application data, and press final submit if all required fields have confirmed values or approved drafts and no human gate remains. The dashboard shows progress and pauses. The initial approval is sufficient for a clean final submission.
2. **Draft for review.** The click starts inspection and preparation. The worker may traverse non-final pages using confirmed facts to reveal later requirements; the UI makes clear that some portals save partial applications during navigation. It stops before final submit and presents an editable packet. The user can then take over the browser or explicitly authorize completion with the agent.

Neither choice is tied to a score range. The chosen mode is stored on the run and can be changed only by an explicit user action. A paused run can be cancelled; cancellation does not imply an external submission was undone.

## Worker execution model

A Python-owned `application_runs` record holds job ID, mode, status, current checkpoint, lease, timestamps, error, and submission-attempt marker. One active run per job prevents duplicate workers. Append-only run events capture transitions and field keys without duplicating sensitive values. Agent-produced plans, question drafts, and evidence go to staging; Python validates and merges them through typed interfaces.

The worker is a separate local CLI/process, not a Streamlit callback. It claims one run, verifies that the posting is active and the description is source-backed, opens the employer application in an isolated visible Playwright profile, and creates documents through the existing bridges. The browser profile is local, access-restricted, and ignored by Git; passwords are handled by the user's browser or password manager, not the application database.

**Provenance rule (design call):** Candidate-owned `user/` profile files and explicitly user-confirmed `application_facts` can support ordinary factual answers such as contact details, employment history, education, and documented skills. A generated resume or cover letter is an output, never independent evidence for a new fact. Job-specific narrative answers are drafts with a visible source trail; if the answer requires a claim absent from those sources, the worker pauses for approval. Work authorization, compensation expectations, demographic disclosures, legal attestations, and consent require explicit facts or direct user action even if a model could infer a likely answer. A profile synchronization check must pass before using `user/master_cv.md` as evidence.

The main loop is:

1. Observe the current page, URL, visible controls, required markers, validation messages, and navigation actions. Save a checkpoint.
2. Match fields to confirmed facts and already approved job-specific answers. Draft missing narrative answers with supporting evidence. If a draft requires user approval, pause before entering or submitting it.
3. Fill and verify controls, upload existing artifacts, and save field outcomes. Never treat a nonempty prefill as a reviewed fact without provenance.
4. Click a non-final Next/Continue action only within the run's authorization. Observe the next page and repeat. Revisit generated documents or uploaded files if newly revealed requirements demand it.
5. At a final-submit control, enforce the run mode and readiness policy. Record a submission-attempt marker before clicking. After clicking, capture a confirmation page, receipt/reference number, or other reliable employer acknowledgment. If confirmation is ambiguous, mark `submission_uncertain` and stop automatic retries.

Provider adapters can override navigation and field handling for complex ATS portals. The generic handler is only eligible when it can positively identify the active form, fields, Next action, and final-submit action. Unsupported controls pause the run; they do not trigger guessed clicks.

## Human handoff

When an account, email link, MFA, CAPTCHA, consent, or unknown answer blocks the run, the worker sets `needs_user` with a specific reason and leaves the application browser available for takeover. The dashboard links to the run, shows its current page and drafted answer if applicable, and offers **Resume** after the user completes or approves the gate. On resume, the worker re-inspects the live page before acting; it does not assume the earlier DOM or URL is unchanged.

If the process restarts, the worker reopens the isolated browser profile and reconciles the portal's current state against the last checkpoint. Some portals keep only in-memory or session-scoped wizard state; in those cases, the worker may need to replay earlier non-final steps or ask for a new handoff. It must never replay final submission automatically.

## Data and state

Suggested run states: `queued`, `inspecting`, `preparing`, `filling`, `needs_user`, `ready_for_review`, `submitting`, `submitted`, `submission_uncertain`, `failed`, and `cancelled`. A separate pause reason distinguishes account setup, verification, consent, question approval, unsupported control, and expired session.

The review packet contains the employer URL, job title, chosen mode, required documents and their paths/previews, proposed answers with source or user approval status, pages inspected, remaining requirements, and any portal-side validation errors. It is a view over durable run and application-workspace data rather than a second canonical store.

`application_submissions` remains the immutable record of what was actually sent. A confirmed submission atomically records the receipt/evidence and moves `tracked_jobs.stage` to `applied`. A user may separately reconcile a submission performed manually in the employer browser.

## Failure and quality rules

- Do not start from a stale or unverified job description; request enrichment or mark the run for attention.
- Do not submit when required fields lack confirmed or specifically approved values, a document is missing, provider validation remains, or a human gate is unresolved.
- Retain only minimal browser evidence needed to diagnose a failure; traces and screenshots may contain personal data and must remain local and excluded from Git.
- Use bounded attempts and leases for pre-submit work. `submission_uncertain` requires inspection or user reconciliation before another submit attempt.
- Measure time from approval to prepared packet/submission, number of handoffs, and portal success rate by provider to guide adapter work.

## Delivery order

1. Add the two Quick Review actions and a durable application-run model/CLI. Keep existing tracking behavior available through those actions.
2. Move inspection and document generation out of Streamlit into the worker; surface progress and a consolidated packet.
3. Implement page-by-page browser checkpoints and human handoff on one supported provider and a bounded generic path.
4. Add the fully-automate final-submit policy with receipt verification and uncertain-submission handling.
5. Update ADR-019, `DATA_CONTRACT.md`, dashboard guidance, and provider-specific tests as the design is implemented.

## Acceptance scenarios

- Any evaluated job, regardless of fit score, displays both choices; either starts exactly one run with the selected mode.
- A multi-page form reveals a later question; the worker captures it, drafts an answer, pauses for approval, and resumes at the current page.
- A portal requires an account and email verification; the worker pauses in a visible browser, the user completes the gate, and the worker re-inspects and continues.
- A clean fully-automate run submits once, captures employer confirmation, snapshots the sent data, and marks the job Applied.
- A draft-for-review run produces the packet and does not submit until a subsequent user action.
- A click with no clear confirmation enters `submission_uncertain`; no automatic retry can produce a duplicate submission.

## Builder decisions left open

The builder may choose exact table/column names, worker launch mechanism, and per-provider locator strategies while preserving this user-facing contract and the staging/canonical boundary.
