# Job Source Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run bounded source discovery and hand current-run verified jobs to the durable agent evaluation queue.

**Architecture:** Reuse existing adapters and SQLite storage. A shared scan ID joins board, ATS and career results; Python validates staging and agents evaluate selected current-run jobs.

**Tech Stack:** Python 3, SQLite, Pydantic, Streamlit, pytest, Codex heartbeat.

**Spec:** [Job source refresh design](../specs/2026-11-10-job-source-refresh-design.md)

## Global Constraints

- Preserve Python ownership of canonical data.
- Do not resume scheduled jobs that the user previously stopped.
- Restrict routine direct discovery to enabled phase 1–2 boards.
- Keep historical evaluation backlog enrollment explicit.

## Review Focus

- Missing or malformed staging candidates must not partially merge.
- A stale source with old jobs must not look healthy.
- A dry run must not insert jobs or log runs.
- New jobs without verified descriptions must remain deferred.
- A scheduled evaluation claim must match the current scan ID and explicit IDs.

## Tasks

- [x] Add job-candidate staging merge through `save_jobs` and test queue state.
- [x] Add source-channel schema, legacy normalization, dashboard display and migration test.
- [x] Add source freshness status and test stale historical results.
- [x] Add bounded shared-ID discovery CLI, career rotation and model-free career pass.
- [x] Create a paused Codex heartbeat for discovery and current-run evaluation.
- [x] Run the full test suite and document the workflow and ADR.
