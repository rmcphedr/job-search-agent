"""Jobs view for the Streamlit dashboard."""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from src.database.db import get_database_path
from src.ui.data_loader import JOBS_DISPLAY_COLUMNS, load_jobs_from_db
from src.ui.job_detail_view import render_job_detail_view
from src.ui.session_utils import select_company, select_job

JOBS_PAGE_SIZE = 20


def render_jobs_view() -> None:
    """Render the jobs table, filters, and job detail panel."""
    if st.session_state.get("show_job_detail") and st.session_state.get("selected_job_id"):
        render_job_detail_view()
        return

    st.header("Jobs")
    st.caption(
        "Job postings from career pages and board discovery. "
        "Board jobs have keyword scores until agent fit evaluation runs."
    )

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
                "Run board discovery (`python -m src.jobs.run_board_discovery`) "
                "or career-page discovery from the Companies page."
            )
        return

    st.metric("Total jobs", len(frame))
    filtered = _render_job_filter_form(frame)

    list_columns = [column for column in JOBS_DISPLAY_COLUMNS if column in filtered.columns]
    table = filtered[list_columns].copy()
    if "active" in table.columns:
        table["active"] = table["active"].map(_format_active)

    total_filtered = len(table)
    total_pages = max(1, math.ceil(total_filtered / JOBS_PAGE_SIZE))
    page = int(st.session_state.get("jobs_page_number", 1))
    page = max(1, min(page, total_pages))
    st.session_state.jobs_page_number = page

    start = (page - 1) * JOBS_PAGE_SIZE
    end = start + JOBS_PAGE_SIZE
    page_table = table.iloc[start:end]

    st.subheader("Job list")
    st.caption(
        f"Showing {start + 1}–{min(end, total_filtered)} of {total_filtered} filtered jobs "
        f"({len(frame)} total) · page {page}/{total_pages}"
    )

    nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
    with nav_col1:
        if st.button("Previous", disabled=page <= 1, key="jobs_page_prev"):
            st.session_state.jobs_page_number = page - 1
            st.rerun()
    with nav_col2:
        st.write("")
        st.write(f"Page **{page}** of **{total_pages}**")
    with nav_col3:
        if st.button("Next", disabled=page >= total_pages, key="jobs_page_next"):
            st.session_state.jobs_page_number = page + 1
            st.rerun()

    column_config = {
        "url": st.column_config.LinkColumn("url"),
        "fit_score": st.column_config.NumberColumn("fit_score", format="%.2f"),
        "keyword_score": st.column_config.NumberColumn("keyword_score", format="%.2f"),
    }
    st.dataframe(
        page_table,
        width="stretch",
        hide_index=True,
        column_config=column_config,
    )

    if filtered.empty:
        st.info("No jobs match the current filters.")
        return

    st.subheader("Open Job Detail")
    page_filtered = filtered.iloc[start:end]
    job_ids = page_filtered["job_id"].astype(str).tolist()
    job_labels = [_job_label(row) for _, row in page_filtered.iterrows()]
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

    selected = page_filtered[page_filtered["job_id"].astype(str) == selected_job_id].iloc[0]
    preview_col1, preview_col2 = st.columns(2)
    with preview_col1:
        st.markdown(f"**Title:** {selected.get('title', '')}")
        st.markdown(f"**Company:** {selected.get('company_name', '')}")
        if "source_board" in selected:
            st.markdown(f"**Source board:** {selected.get('source_board', '—')}")
    with preview_col2:
        fit_score = selected.get("fit_score")
        fit_text = f"{float(fit_score):.1f}" if pd.notna(fit_score) else "Pending evaluation"
        st.markdown(f"**Fit score:** {fit_text}")
        if "keyword_score" in selected and pd.notna(selected.get("keyword_score")):
            st.markdown(f"**Keyword score:** {float(selected['keyword_score']):.2f}")
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
            "source_boards": [],
            "min_fit_score": 0.0,
            "active_only": True,
            "include_unevaluated": True,
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
            board_options = _sorted_unique(frame["source_board"]) if "source_board" in frame.columns else []
            selected_boards = st.multiselect(
                "Source board",
                options=board_options,
                default=defaults.get("source_boards", []),
                key="jobs_filter_source_board",
            )
        with col4:
            active_only = st.checkbox(
                "Active only",
                value=defaults["active_only"],
                key="jobs_filter_active_only",
            )

        col5, col6, col7 = st.columns(3)
        with col5:
            min_fit_score = st.slider(
                "Minimum fit score",
                min_value=0.0,
                max_value=10.0,
                value=float(defaults["min_fit_score"]),
                step=0.5,
                key="jobs_filter_min_fit_score",
            )
        with col6:
            include_unevaluated = st.checkbox(
                "Include unevaluated",
                value=defaults.get("include_unevaluated", True),
                help="Show board-discovered jobs before agent fit evaluation.",
                key="jobs_filter_include_unevaluated",
            )
        with col7:
            keyword_query = st.text_input(
                "Keyword search",
                value=defaults["keyword_query"],
                placeholder="Python, machine learning, bioinformatics...",
                key="jobs_filter_keyword",
            )

        apply_filters = st.form_submit_button("Apply filters", width="stretch")

    if apply_filters:
        st.session_state.job_filter_defaults = {
            "companies": selected_companies,
            "locations": selected_locations,
            "source_boards": selected_boards,
            "min_fit_score": min_fit_score,
            "active_only": active_only,
            "include_unevaluated": include_unevaluated,
            "keyword_query": keyword_query,
        }
        st.session_state.jobs_page_number = 1

    active = st.session_state.job_filter_defaults
    filtered = frame.copy()
    if active["companies"]:
        filtered = filtered[filtered["company_name"].isin(active["companies"])]
    if active["locations"]:
        filtered = filtered[filtered["location"].fillna("").isin(active["locations"])]
    if active.get("source_boards") and "source_board" in filtered.columns:
        filtered = filtered[filtered["source_board"].fillna("").isin(active["source_boards"])]
    if active["active_only"]:
        filtered = filtered[filtered["active"].astype(str).isin({"1", "True", "true"})]

    filtered["fit_score"] = pd.to_numeric(filtered["fit_score"], errors="coerce")
    min_score = float(active["min_fit_score"])
    if active.get("include_unevaluated", True):
        filtered = filtered[filtered["fit_score"].isna() | (filtered["fit_score"] >= min_score)]
    else:
        filtered = filtered[filtered["fit_score"].notna() & (filtered["fit_score"] >= min_score)]

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
            "source_board",
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
    fit_text = f"{float(fit_score):.1f}" if pd.notna(fit_score) else "pending"
    return f"{row.get('company_name', 'Unknown')} | {row.get('title', 'Untitled')} | fit={fit_text}"
