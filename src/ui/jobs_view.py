"""Jobs view for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.database.db import get_database_path
from src.ui.data_loader import JOBS_DISPLAY_COLUMNS, load_jobs_from_db
from src.ui.job_detail_view import render_job_detail_view
from src.ui.session_utils import select_company, select_job


def render_jobs_view() -> None:
    """Render the jobs table, filters, and job detail panel."""
    if st.session_state.get("show_job_detail") and st.session_state.get("selected_job_id"):
        render_job_detail_view()
        return

    st.header("Jobs")
    st.caption("Job postings stored in SQLite with fit scores and keyword matches.")

    db_path = get_database_path()
    try:
        frame = load_jobs_from_db()
    except Exception as exc:
        st.error(f"Failed to load jobs: {exc}")
        return

    if frame.empty:
        if not db_path.exists():
            st.warning(
                f"Database not found at `{db_path}`. "
                "Run `python -m src.database.init_db` and job discovery first."
            )
        else:
            st.warning(
                "No jobs found in the database. "
                "Use **Run Job Discovery** on the Companies page to populate job_postings."
            )
        return

    st.metric("Total jobs", len(frame))
    filtered = _render_job_filter_form(frame)

    list_columns = list(JOBS_DISPLAY_COLUMNS)
    table = filtered[list_columns].copy()
    table["active"] = table["active"].map(_format_active)

    st.subheader("Job list")
    st.caption(f"Showing {len(table)} of {len(frame)} jobs")
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "url": st.column_config.LinkColumn("url"),
            "fit_score": st.column_config.NumberColumn("fit_score", format="%.2f"),
        },
    )

    if filtered.empty:
        st.info("No jobs match the current filters.")
        return

    st.subheader("Open Job Detail")
    job_ids = filtered["job_id"].astype(str).tolist()
    job_labels = [_job_label(row) for _, row in filtered.iterrows()]
    label_by_id = dict(zip(job_ids, job_labels, strict=False))

    detail_col1, detail_col2 = st.columns([3, 1])
    with detail_col1:
        selected_job_id = st.selectbox(
            "Select a job",
            options=job_ids,
            format_func=lambda job_id: label_by_id.get(job_id, job_id),
            key="jobs_page_selected_job_id",
        )
    with detail_col2:
        st.write("")
        st.write("")
        if st.button("View Job Detail", width="stretch", key="view_job_detail_button"):
            select_job(selected_job_id)
            st.rerun()

    selected = filtered[filtered["job_id"].astype(str) == selected_job_id].iloc[0]
    preview_col1, preview_col2 = st.columns(2)
    with preview_col1:
        st.markdown(f"**Title:** {selected.get('title', '')}")
        st.markdown(f"**Company:** {selected.get('company_name', '')}")
    with preview_col2:
        st.markdown(f"**Fit score:** {selected.get('fit_score', '—')}")
        if st.button("View Company Profile", key="jobs_view_company_profile_button"):
            select_company(str(selected.get("company_name", "")))
            st.session_state.show_job_detail = False
            st.rerun()


def _render_job_filter_form(frame: pd.DataFrame) -> pd.DataFrame:
    defaults = st.session_state.setdefault(
        "job_filter_defaults",
        {
            "companies": [],
            "locations": [],
            "min_fit_score": 0.0,
            "active_only": True,
            "keyword_query": "",
        },
    )

    with st.form("job_filters_form", clear_on_submit=False):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            company_options = _sorted_unique(frame["company_name"])
            selected_companies = st.multiselect(
                "Company",
                options=company_options,
                default=defaults["companies"],
                key="jobs_filter_company",
            )
        with col2:
            location_options = _sorted_unique(frame["location"])
            selected_locations = st.multiselect(
                "Location",
                options=location_options,
                default=defaults["locations"],
                key="jobs_filter_location",
            )
        with col3:
            min_fit_score = st.slider(
                "Minimum fit score",
                min_value=0.0,
                max_value=10.0,
                value=float(defaults["min_fit_score"]),
                step=0.5,
                key="jobs_filter_min_fit_score",
            )
        with col4:
            active_only = st.checkbox(
                "Active only",
                value=defaults["active_only"],
                key="jobs_filter_active_only",
            )

        keyword_query = st.text_input(
            "Keyword search",
            value=defaults["keyword_query"],
            placeholder="Python, Machine Learning, Bioinformatics, Neuroscience, fMRI, Healthcare...",
            help="Search title, description, matched keywords, location, and fit reason.",
            key="jobs_filter_keyword",
        )
        apply_filters = st.form_submit_button("Apply filters", width="stretch")

    if apply_filters:
        st.session_state.job_filter_defaults = {
            "companies": selected_companies,
            "locations": selected_locations,
            "min_fit_score": min_fit_score,
            "active_only": active_only,
            "keyword_query": keyword_query,
        }

    active = st.session_state.job_filter_defaults
    filtered = frame.copy()
    if active["companies"]:
        filtered = filtered[filtered["company_name"].isin(active["companies"])]
    if active["locations"]:
        filtered = filtered[filtered["location"].fillna("").isin(active["locations"])]
    if active["active_only"]:
        filtered = filtered[filtered["active"].astype(str).isin({"1", "True", "true"})]
    filtered["fit_score"] = pd.to_numeric(filtered["fit_score"], errors="coerce")
    filtered = filtered[filtered["fit_score"].fillna(0) >= active["min_fit_score"]]

    keyword_query = active["keyword_query"].strip()
    if keyword_query:
        needle = keyword_query.lower()
        search_columns = [
            "company_name",
            "title",
            "location",
            "fit_reason",
            "description",
            "matched_keywords",
        ]
        mask = pd.Series(False, index=filtered.index)
        for column in search_columns:
            if column in filtered.columns:
                mask |= filtered[column].fillna("").astype(str).str.lower().str.contains(
                    needle, regex=False
                )
        filtered = filtered[mask]

    return filtered


def _sorted_unique(series: pd.Series) -> list[str]:
    values = {
        str(value).strip()
        for value in series.fillna("").tolist()
        if str(value).strip()
    }
    return sorted(values)


def _format_active(value: object) -> str:
    text = str(value).strip().lower()
    if text in {"1", "true"}:
        return "Yes"
    if text in {"0", "false"}:
        return "No"
    return str(value)


def _job_label(row: pd.Series) -> str:
    fit_score = row.get("fit_score")
    fit_text = f"{float(fit_score):.1f}" if pd.notna(fit_score) else "—"
    return f"{row.get('company_name', 'Unknown')} | {row.get('title', 'Untitled')} | fit={fit_text}"
