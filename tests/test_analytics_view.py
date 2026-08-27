"""Tests for application-flow analytics."""

from src.ui.analytics_view import _build_application_flow


def test_application_flow_includes_jobs_that_advanced_beyond_applied() -> None:
    tracked = [
        {"job_id": 1, "stage": "tracked", "applied_at": None},
        {"job_id": 2, "stage": "applied", "applied_at": "2026-08-01T12:00:00Z"},
        {"job_id": 3, "stage": "interviewing", "applied_at": "2026-08-02T12:00:00Z"},
        {"job_id": 4, "stage": "rejected", "applied_at": "2026-08-03T12:00:00Z"},
    ]

    history = [
        {"job_id": 2, "stage": "applied"},
        {"job_id": 3, "stage": "applied"},
        {"job_id": 3, "stage": "interviewing"},
        {"job_id": 4, "stage": "applied"},
        {"job_id": 4, "stage": "interviewing"},
        {"job_id": 4, "stage": "rejected"},
    ]

    labels, sources, targets, counts, applied_jobs = _build_application_flow(tracked, history)

    assert labels == ["Applications submitted", "No response", "Interviewing", "Rejected"]
    assert [(labels[source], labels[target], count) for source, target, count in zip(sources, targets, counts)] == [
        ("Applications submitted", "No response", 3),
        ("No response", "Interviewing", 2),
        ("Interviewing", "Rejected", 1),
    ]
    assert [row["job_id"] for row in applied_jobs] == [2, 3, 4]


def test_application_flow_is_empty_without_application_dates() -> None:
    assert _build_application_flow([{"stage": "applying", "applied_at": None}], []) == (
        ["Applications submitted"],
        [],
        [],
        [],
        [],
    )
