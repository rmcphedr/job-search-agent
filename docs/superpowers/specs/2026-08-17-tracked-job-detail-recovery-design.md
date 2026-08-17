# Tracked Job Detail Recovery Design

## Problem

The Tracking table reads current rows directly from SQLite, but the tracked-job detail view resolves its job through the cached dashboard-wide jobs DataFrame. When a job is added or updated outside the cache-refresh path, the table can show the tracked job while the detail lookup returns no row and displays “This tracked job is no longer available.” The current error path then clears the navigation state during the same render without rerunning or presenting a usable recovery control, leaving the user on a dead-end screen.

The Thales posting (job ID 705) remains present and active in SQLite with its stored description and tracking metadata. No data repair is required.

## Design

Add a focused, uncached database lookup for a single job posting, joined to its company, and use it in the tracked-job detail and preparation views. Collection views may continue using the cached DataFrame because caching is useful for browsing and ranking; user-selected tracked records must reflect current canonical state.

If either the posting or its tracking record is genuinely missing, render the existing error plus an explicit “← All tracked jobs” button. Clicking the button clears the selected job and detail mode, then reruns Streamlit so the table is immediately restored. Do not silently mutate navigation state while rendering the error.

## Components and Data Flow

- `src/ui/data_loader.py` exposes a single-record loader accepting an integer or string job ID and returning the same dictionary shape used by existing detail views.
- The loader queries `job_postings` joined to `companies` using a parameterized job-ID predicate and returns `None` for invalid or absent IDs.
- `src/ui/tracking_view.py` uses the uncached loader anywhere a tracked workflow needs one specific posting.
- The unavailable-state renderer owns the error message and recovery button behavior so detail and preparation paths behave consistently.

## Error Handling

Invalid job IDs, missing postings, and missing tracking rows all produce the unavailable state without raising an exception. The recovery button always returns to the tracking table. Database operational errors retain the project’s existing logging/error conventions and are not disguised as successful lookups.

## Testing

- Prove the single-record loader sees a newly inserted posting even when the cached collection loader represents older data.
- Prove it returns `None` for an invalid or absent job ID.
- Prove the unavailable state renders a Back control and only clears navigation when that control is activated.
- Run focused UI/data-loader tests, then the full test suite.

## Non-goals

- Changing the Thales posting’s active flag or canonical content.
- Removing caching from collection views.
- Refactoring unrelated dashboard navigation or job discovery behavior.
