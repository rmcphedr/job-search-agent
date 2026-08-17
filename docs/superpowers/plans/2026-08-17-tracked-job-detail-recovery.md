# Tracked Job Detail Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure tracked job detail screens read the current SQLite record and always provide a working route back to the tracking table when a record is unavailable.

**Architecture:** Keep cached DataFrame loading for collection views, but add a parameterized uncached lookup for one selected posting. Centralize the unavailable tracked-job UI so detail and preparation modes render the same error and explicit recovery button.

**Tech Stack:** Python 3.11, SQLite, pandas, Streamlit, pytest, Streamlit AppTest.

## Global Constraints

- Do not modify canonical job or tracking data.
- Do not remove caching from collection views.
- Preserve the dictionary fields currently returned by `get_job_by_id`.
- Preserve unrelated user changes and pre-existing baseline failures.

---

### Task 1: Current single-job database lookup

**Files:**
- Modify: `src/ui/data_loader.py`
- Create: `tests/test_data_loader.py`

**Interfaces:**
- Consumes: `get_connection()` and the selected `job_id: int | str`.
- Produces: `get_current_job_by_id(job_id: int | str) -> dict[str, Any] | None`.

- [x] **Step 1: Write failing lookup tests**

Create a temporary SQLite database containing one company and posting. Patch `src.ui.data_loader.get_connection`, then assert `get_current_job_by_id("705")` returns job ID 705, the company name, title, and description. Assert malformed and absent IDs return `None`.

- [x] **Step 2: Run tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_data_loader.py -q`

Expected: collection fails because `get_current_job_by_id` does not exist.

- [x] **Step 3: Implement the minimal uncached lookup**

Add a single-record SQL query using the same selected columns as `JOBS_QUERY`, a `WHERE j.job_id = ?` predicate, and no Streamlit cache decorator. Normalize the identifier with `int()`; return `None` for `TypeError` or `ValueError`. Open and close the connection around the query and apply the same nullable/legacy fit-field normalization used by collection loading.

- [x] **Step 4: Run tests to verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_data_loader.py -q`

Expected: all tests pass.

### Task 2: Tracked workflow recovery UI

**Files:**
- Modify: `src/ui/tracking_view.py`
- Create: `tests/test_tracking_view.py`

**Interfaces:**
- Consumes: `get_current_job_by_id(job_id)` and Streamlit session state.
- Produces: `_render_unavailable_job() -> None`, rendering the error and a button that calls `_back_to_table()` followed by `st.rerun()`.

- [x] **Step 1: Write failing UI behavior test**

Use Streamlit AppTest to render `_render_unavailable_job` with detail-mode session state. Assert the error and “← All tracked jobs” button are present. Click the button, rerun, and assert mode becomes `table` and the selected job ID becomes `None`.

- [x] **Step 2: Run test to verify RED**

Run: `.venv/bin/python -m pytest tests/test_tracking_view.py -q`

Expected: collection or execution fails because `_render_unavailable_job` does not exist.

- [x] **Step 3: Implement current lookup and recovery rendering**

Import `get_current_job_by_id`; use it for each specific tracked-workflow posting lookup in `tracking_view.py`. Replace the current unavailable branch with `_render_unavailable_job()`, which renders the existing error, shows the recovery button, and changes state only after a click.

- [x] **Step 4: Run focused tests to verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_data_loader.py tests/test_tracking_view.py tests/test_tracked_jobs.py -q`

Expected: all focused tests pass.

- [x] **Step 5: Run regression verification**

Run: `.venv/bin/python -m pytest tests -q`

Expected: new and relevant tests pass; only the three documented pre-existing `tests/test_application_workspace.py` failures may remain. Run `git diff --check` and inspect the final diff.
