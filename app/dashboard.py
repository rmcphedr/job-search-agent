"""Streamlit dashboard entry point for job-search-agent."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.ui.analytics_view import render_analytics_view
from src.ui.company_view import render_company_view
from src.ui.data_loader import global_search
from src.ui.evaluations_view import render_evaluations_view
from src.ui.jobs_view import render_jobs_view
from src.ui.profile_view import render_profile_view
from src.ui.session_utils import init_session_state, render_selection_sidebar, select_company, select_job
from src.ui.tracking_view import render_tracking_view

PAGES = {
    "Tracking": render_tracking_view,
    "Companies": render_company_view,
    "Company Fit": render_evaluations_view,
    "Jobs": render_jobs_view,
    "Analytics": render_analytics_view,
    "Profile / Settings": render_profile_view,
}


def _render_global_search() -> None:
    st.sidebar.subheader("Search Everywhere")
    with st.sidebar.form("global_search_form", clear_on_submit=False):
        query = st.text_input(
            "Global search",
            placeholder="Company, industry, job title, keywords...",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Search", width="stretch")

    if submitted:
        st.session_state.global_search_query = query.strip()
        st.session_state.global_search_results = None

    active_query = st.session_state.get("global_search_query", "")
    if not active_query:
        return

    if st.session_state.get("global_search_results") is None:
        st.session_state.global_search_results = global_search(active_query)

    results = st.session_state.global_search_results
    company_hits = results["companies"]
    job_hits = results["jobs"]

    with st.sidebar.expander(
        f"Results for '{active_query[:40]}' ({len(company_hits)} co, {len(job_hits)} jobs)",
        expanded=True,
    ):
        if company_hits.empty and job_hits.empty:
            st.caption("No matches found.")
            return

        if not company_hits.empty:
            st.markdown("**Companies**")
            for _, row in company_hits.head(10).iterrows():
                name = row["company_name"]
                if st.button(f"Company: {name}", key=f"search_company_{name}"):
                    select_company(name)
                    st.rerun()

        if not job_hits.empty:
            st.markdown("**Jobs**")
            for _, row in job_hits.head(10).iterrows():
                label = f"{row['company_name']} | {row['title']}"
                job_id = row["job_id"]
                if st.button(label, key=f"search_job_{job_id}"):
                    select_job(job_id)
                    st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Job Search Agent",
        page_icon="🔎",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_session_state()
    st.session_state.setdefault("global_search_results", None)
    st.session_state.setdefault("main_navigation", "Tracking")

    st.sidebar.title("Job Search Agent")
    st.sidebar.caption("Company and job research control panel")
    page = st.sidebar.radio("Navigation", list(PAGES.keys()), key="main_navigation")
    st.sidebar.divider()
    _render_global_search()
    st.sidebar.divider()
    render_selection_sidebar()
    st.sidebar.markdown(
        "Data sources:\n"
        "- `data/company_inventory.csv`\n"
        "- `data/company_evaluations.csv`\n"
        "- `data/job_search.db`"
    )

    PAGES[page]()


if __name__ == "__main__":
    main()
