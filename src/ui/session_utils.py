"""Session state helpers for dashboard navigation."""

from __future__ import annotations

import streamlit as st

_PENDING_NAVIGATION_KEY = "_pending_main_navigation"


def init_session_state() -> None:
    st.session_state.setdefault("selected_company", None)
    st.session_state.setdefault("selected_job_id", None)
    st.session_state.setdefault("show_company_detail", False)
    st.session_state.setdefault("show_job_detail", False)
    st.session_state.setdefault("global_search_query", "")
    st.session_state.setdefault("global_search_results", None)
    st.session_state.setdefault("tracking_selected_job_id", None)
    st.session_state.setdefault("tracking_view_mode", "table")
    st.session_state.setdefault("main_navigation", "Review")


def apply_pending_navigation() -> None:
    """Apply deferred page navigation before the sidebar radio widget is created."""
    pending = st.session_state.pop(_PENDING_NAVIGATION_KEY, None)
    if pending is not None:
        st.session_state.main_navigation = pending


def _request_navigation(page: str) -> None:
    st.session_state[_PENDING_NAVIGATION_KEY] = page


def select_company(company_name: str) -> None:
    st.session_state.selected_company = company_name
    st.session_state.show_company_detail = False
    st.session_state.show_job_detail = False
    _request_navigation("Companies")


def select_job(job_id: int | str) -> None:
    st.session_state.selected_job_id = str(job_id)
    st.session_state.show_job_detail = True


def select_tracking_job(job_id: int | str) -> None:
    st.session_state.tracking_selected_job_id = str(job_id)
    st.session_state.show_job_detail = False


def navigate_to_tracking() -> None:
    _request_navigation("Tracking")


def clear_company_detail() -> None:
    st.session_state.show_company_detail = False


def clear_job_detail() -> None:
    st.session_state.show_job_detail = False
    st.session_state.selected_job_id = None


def render_selection_sidebar() -> None:
    if st.session_state.get("selected_company"):
        st.sidebar.caption(f"Selected company: **{st.session_state.selected_company}**")
    if st.session_state.get("selected_job_id"):
        st.sidebar.caption(f"Selected job ID: **{st.session_state.selected_job_id}**")
