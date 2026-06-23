"""Session state helpers for dashboard navigation."""

from __future__ import annotations

import streamlit as st


def init_session_state() -> None:
    st.session_state.setdefault("selected_company", None)
    st.session_state.setdefault("selected_job_id", None)
    st.session_state.setdefault("show_company_detail", False)
    st.session_state.setdefault("show_job_detail", False)
    st.session_state.setdefault("global_search_query", "")
    st.session_state.setdefault("global_search_results", None)


def select_company(company_name: str) -> None:
    st.session_state.selected_company = company_name
    st.session_state.show_company_detail = True
    st.session_state.show_job_detail = False


def select_job(job_id: int | str) -> None:
    st.session_state.selected_job_id = str(job_id)
    st.session_state.show_job_detail = True


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
