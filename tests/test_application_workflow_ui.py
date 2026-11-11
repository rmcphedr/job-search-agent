"""Dashboard controls exercise durable APIs without running a browser."""
from unittest.mock import MagicMock
import pytest
from src.ui import review_view, tracking_view, operations_view

@pytest.fixture
def ui(monkeypatch):
    fake = MagicMock()
    fake.columns.side_effect = lambda spec, **kw: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
    fake.button.return_value = False
    fake.text_area.side_effect = lambda label, value="", **kw: value
    fake.selectbox.side_effect = lambda label, options, index=0, **kw: options[index]
    for module in (review_view, tracking_view, operations_view):
        monkeypatch.setattr(module, "st", fake)
    return fake

@pytest.mark.parametrize("score", [1, 5, 9])
@pytest.mark.parametrize("label,mode", [("Fully automate", "fully_automate"), ("Draft for review", "draft_for_review")])
def test_equal_choices_enqueue_job_mode(ui, monkeypatch, score, label, mode):
    enqueue = MagicMock()
    monkeypatch.setattr(review_view, "enqueue_application", enqueue)
    monkeypatch.setattr(review_view, "_after_decision", MagicMock())
    ui.button.side_effect = lambda text, **kw: text == label
    monkeypatch.setattr(review_view, "get_review_decisions", lambda: {})
    monkeypatch.setattr(review_view, "get_tracked_stage_map", lambda: {})
    import pandas as pd
    inbox = review_view._build_inbox(pd.DataFrame([{"job_id": 42, "active": 1,
        "fit_score": score, "fit_details": {"qualification_assessment": [{"requirement": "Python"}]},
        "date_found": "2026-11-11"}]), 0)
    assert len(inbox) == 1
    review_view._render_actions(int(inbox.iloc[0]["job_id"]), 1)
    assert {"Fully automate", "Draft for review"} <= {call.args[0] for call in ui.button.call_args_list}
    enqueue.assert_called_once_with(42, mode)


def packet(status="needs_user", mode="draft_for_review"):
    return {"run": {"run_id": 3, "status": status, "mode": mode, "pause_reason": "question_approval", "submission_attempted_at": None},
            "session": {"application_url": "https://example.test", "current_page": "Questions"},
            "fields": [{"field_key": "motivation", "label": "Why?", "value": "", "status": "pending"}],
            "drafts": {"motivation": {"answer": "Evidence based draft", "evidence_refs": ["user/proof_points.md"], "approval_status": "approval_required"}},
            "artifacts": {}, "pages": [], "remaining": ["motivation"], "validation": [], "steps": []}


def setup_packet(monkeypatch, value):
    monkeypatch.setattr(tracking_view, "get_application_run", lambda job: value["run"])
    monkeypatch.setattr(tracking_view, "get_review_packet", lambda run: value)
    monkeypatch.setattr(tracking_view, "refresh_data", MagicMock())


def test_answer_edit_approval_and_resume(ui, monkeypatch):
    setup_packet(monkeypatch, packet())
    approve, resume = MagicMock(), MagicMock()
    monkeypatch.setattr(tracking_view, "approve_answer", approve)
    monkeypatch.setattr(tracking_view, "resume_application", resume)
    ui.text_area.return_value = "My edited answer"
    ui.text_area.side_effect = None
    ui.button.side_effect = lambda text, **kw: text in {"Approve answer", "Resume"}
    tracking_view._render_application_run(42)
    approve.assert_called_once_with(3, "motivation", "My edited answer")
    resume.assert_called_once_with(3)

@pytest.mark.parametrize("label,api", [("Save mode", "set_application_mode"), ("Cancel application", "cancel_application")])
def test_explicit_run_controls(ui, monkeypatch, label, api):
    setup_packet(monkeypatch, packet())
    action = MagicMock()
    monkeypatch.setattr(tracking_view, api, action)
    ui.button.side_effect = lambda text, **kw: text == label
    tracking_view._render_application_run(42)
    assert action.call_count == 1


def test_draft_packet_and_uncertain_have_no_submit_or_retry(ui, monkeypatch):
    for status in ("ready_for_review", "submission_uncertain"):
        setup_packet(monkeypatch, packet(status))
        ui.button.reset_mock()
        tracking_view._render_application_run(42)
        labels = [call.args[0].lower() for call in ui.button.call_args_list]
        assert not any("retry" in label for label in labels)
        if status == "submission_uncertain":
            assert "resume" not in labels
            assert not any("submit" in label for label in labels)
            assert ui.error.called
        else:
            assert ui.info.called


def test_metrics_group_completed_and_paused_elapsed_time():
    rows = [{"status": "submitted", "provider": "lever", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:01:00+00:00"},
            {"status": "needs_user", "provider": "lever", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:02:00+00:00"}]
    result = operations_view.application_metrics(rows)
    assert result["count"].sum() == 2
    assert set(result["elapsed_seconds"]) == {60, 120}


def test_ready_packet_requires_explicit_completion(ui, monkeypatch):
    setup_packet(monkeypatch, packet("ready_for_review"))
    mode, transition = MagicMock(), MagicMock()
    monkeypatch.setattr(tracking_view, "set_application_mode", mode)
    monkeypatch.setattr(tracking_view, "transition_application", transition)
    tracking_view._render_application_run(42)
    mode.assert_not_called()
    transition.assert_not_called()
    ui.button.side_effect = lambda text, **kw: text == "Authorize agent to finish and submit"
    tracking_view._render_application_run(42)
    mode.assert_called_once_with(3, "fully_automate")
    transition.assert_called_once_with(3, "queued")
