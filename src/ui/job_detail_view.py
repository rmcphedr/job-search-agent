"""Full job detail view for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.ui.data_loader import get_job_by_id, parse_fit_reason
from src.ui.session_utils import clear_job_detail, select_company


def render_job_detail_view(job_id: int | str | None = None) -> None:
    """Render a detailed job posting page."""
    target_id = job_id or st.session_state.get("selected_job_id")
    if not target_id:
        st.warning("No job selected.")
        return

    job = get_job_by_id(target_id)
    if job is None:
        st.error("Job not found.")
        if st.button("← Back"):
            clear_job_detail()
            st.rerun()
        return

    if st.button("← Back to Jobs"):
        clear_job_detail()
        st.rerun()

    st.header(job.get("title", "Job Details"))
    st.caption(str(job.get("company_name", "")))

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Company:** {job.get('company_name') or '—'}")
        st.markdown(f"**Location:** {job.get('location') or '—'}")
        st.markdown(f"**Provider:** {job.get('provider') or '—'}")
        st.markdown(f"**Date found:** {job.get('date_found') or '—'}")
    with col2:
        st.markdown(f"**Fit score:** {job.get('fit_score') or '—'}")
        st.markdown(f"**Active:** {_format_active(job.get('active'))}")
        matched = job.get("matched_keywords") or "—"
        st.markdown(f"**Matched keywords:** {matched}")

    url = str(job.get("url") or "").strip()
    btn_col1, btn_col2, btn_col3 = st.columns(3)
    with btn_col1:
        if url:
            st.link_button("Open Job Posting", url, width="stretch")
        else:
            st.button("Open Job Posting", disabled=True, width="stretch")
    with btn_col2:
        if url:
            st.code(url, language=None)
            st.caption("Copy the URL above")
        else:
            st.caption("No URL available")
    with btn_col3:
        if st.button("View Company", width="stretch"):
            select_company(str(job.get("company_name", "")))
            st.rerun()

    st.subheader("Description")
    description = job.get("description")
    if description and str(description).strip():
        st.text_area(
            "Job description",
            value=str(description),
            height=400,
            disabled=True,
            label_visibility="collapsed",
        )
    else:
        st.info("No description stored for this job.")

    st.subheader("Coming Soon")
    future_col1, future_col2, future_col3, future_col4 = st.columns(4)
    with future_col1:
        st.button("Tailor Resume", disabled=True, help="Coming Soon", width="stretch")
    with future_col2:
        st.button("Generate Cover Letter", disabled=True, help="Coming Soon", width="stretch")
    with future_col3:
        st.button("Outreach Generation", disabled=True, help="Coming Soon", width="stretch")
    with future_col4:
        st.button("Application Tracking", disabled=True, help="Coming Soon", width="stretch")


def _format_active(value: object) -> str:
    text = str(value).strip().lower()
    if text in {"1", "true"}:
        return "Yes"
    if text in {"0", "false"}:
        return "No"
    return str(value) if value is not None else "—"
