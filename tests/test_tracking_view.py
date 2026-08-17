"""Focused tests for tracked-job navigation recovery."""

from streamlit.testing.v1 import AppTest


def _unavailable_job_app() -> None:
    import streamlit as st
    from src.ui.tracking_view import _render_unavailable_job

    st.session_state.setdefault("tracking_view_mode", "detail")
    st.session_state.setdefault("tracking_selected_job_id", "705")
    _render_unavailable_job()


def test_unavailable_job_has_working_back_to_tracking_control() -> None:
    app = AppTest.from_function(_unavailable_job_app).run()

    assert app.error[0].value == "This tracked job is no longer available."
    assert app.button[0].label == "← All tracked jobs"
    assert app.session_state["tracking_view_mode"] == "detail"
    assert app.session_state["tracking_selected_job_id"] == "705"

    app.button[0].click().run()

    assert app.session_state["tracking_view_mode"] == "table"
    assert app.session_state["tracking_selected_job_id"] is None
