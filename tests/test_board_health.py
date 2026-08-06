"""Tests for board source health summaries."""

from __future__ import annotations

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_health import (
    BoardRunSnapshot,
    classify_board_health,
    latest_board_run_snapshots,
    parse_board_run_notes,
)


def test_parse_json_board_run_notes() -> None:
    notes = (
        '{"run_id":"20260805T120000Z","boards_checked":2,"raw_jobs_found":10,'
        '"boards":[{"source_id":"jobbank","raw_jobs":5,"queries_run":1,"notes":""},'
        '{"source_id":"biospace","raw_jobs":0,"queries_run":1,"notes":"error: timeout"}]}'
    )
    payload = parse_board_run_notes(notes)
    assert payload["run_id"] == "20260805T120000Z"
    assert len(payload["boards"]) == 2


def test_parse_legacy_board_run_notes() -> None:
    notes = "run_id=20260805T135833Z boards=3 raw=499 filtered=320 inserted=138"
    payload = parse_board_run_notes(notes)
    assert payload["raw_jobs_found"] == 499
    assert payload["inserted"] == 138


def test_latest_board_run_snapshots_uses_most_recent() -> None:
    runs = [
        {
            "completed_at": "2026-08-05T10:00:00",
            "notes": '{"run_id":"a","boards":[{"source_id":"jobbank","raw_jobs":3,"queries_run":1,"notes":""}]}',
        },
        {
            "completed_at": "2026-08-05T11:00:00",
            "notes": '{"run_id":"b","boards":[{"source_id":"jobbank","raw_jobs":7,"queries_run":2,"notes":""}]}',
        },
    ]
    snapshots = latest_board_run_snapshots(runs)
    assert snapshots["jobbank"].raw_jobs == 7


def test_classify_board_health_states() -> None:
    board = BoardSource(
        source_id="jobbank",
        name="Job Bank",
        adapter="jobbank",
        enabled=True,
    )
    healthy, _ = classify_board_health(board, job_total=5, last_run=None)
    assert healthy == "healthy"

    warning, _ = classify_board_health(
        board,
        job_total=0,
        last_run=BoardRunSnapshot(source_id="jobbank", run_at="now", raw_jobs=0, queries_run=2),
    )
    assert warning == "warning"

    error_board = BoardSource(source_id="x", name="X", adapter="jobbank", enabled=True)
    error, _ = classify_board_health(
        error_board,
        job_total=0,
        last_run=BoardRunSnapshot(
            source_id="x",
            run_at="now",
            notes="error: blocked by captcha",
            queries_run=1,
        ),
    )
    assert error == "error"
