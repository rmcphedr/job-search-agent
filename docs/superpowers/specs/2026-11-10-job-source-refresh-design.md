# Job source refresh design

## Intent

Make existing board, employer ATS, and company-career discovery runnable as one
bounded workflow, with current-run jobs ready for structured agent evaluation.
The previously stopped daily alert workflow remains stopped.

## Approach

Use the existing Python adapters and SQLite queue. A new CLI runs enabled
phase 1–2 boards, discovers and refreshes registered employer ATS boards with
fetch caps, and optionally rotates a limited company-career pass. Every path
shares one discovery run ID. The CLI returns verified, queued jobs for an agent
to select, claim and submit through the existing evaluation CLI. A separate
paused Codex heartbeat is ready to invoke the workflow when the user resumes
scheduled jobs.

## Data and UI

The generic staging merger accepts validated `JobCandidate` files and persists
through `save_jobs`. `source_board` holds the original provider and a new
`source_channel` holds the discovery route. Python migration normalizes known
legacy alert labels. Board health uses recent attempts rather than historical
job counts. Dashboard job and board views refresh cached data within five
minutes.

## Constraints

- Python alone owns canonical CSV and SQLite writes.
- Historical jobs never enter a scheduled evaluation claim implicitly.
- The scheduled discovery CLI never calls a model.
- Direct phase-3 scraping, including Indeed and LinkedIn, is outside the
  dependable scheduled path; alert leads can still enter validated staging.
- No account actions or application submissions occur.

## Considered approaches

- Schedule all configured boards: broad but brittle, with restricted sites.
- Schedule reliable lower-phase boards and employer feeds: chosen for bounded,
  observable coverage using existing adapters.
