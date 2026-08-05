"""Jobs view for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.database.db import get_database_path
from src.database.tracked_jobs import (
    STAGE_LABELS,
    get_tracked_job,
    get_tracked_stage_map,
    track_jobs,
    untrack_jobs,
)
from src.ui.actions import refresh_data
from src.ui.data_loader import get_job_by_id, load_jobs_from_db
from src.ui.job_detail_view import render_job_detail_view
from src.ui.session_utils import navigate_to_tracking, select_company, select_job

JOBS_BROWSE_TABLE_KEY = "jobs_browse_table"

BROWSE_COLUMNS = (
    "company_name",
    "title",
    "location",
    "tracking_status",
    "source_board",
    "keyword_score",
    "fit_score",
    "date_found",
    "active",
    "url",
)


def render_jobs_view() -> None:
    """Render the jobs table, filters, and job detail panel."""
    if st.session_state.get("show_job_detail") and st.session_state.get("selected_job_id"):
        render_job_detail_view()
        return

    st.header("Jobs")
    st.caption(
        "Browse discovered postings. Click a row to preview; use Shift+Click and "
        "Cmd/Ctrl+Click to select multiple rows for bulk actions."
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

    filtered = _render_job_filter_form(frame)
    if filtered.empty:
        st.info("No jobs match the current filters.")
        return

    stage_map = get_tracked_stage_map()
    browse_table = _build_browse_table(filtered, stage_map)

    st.metric("Jobs shown", len(browse_table))
    st.caption("Click rows to select. Shift+Click extends selection; Cmd/Ctrl+Click toggles rows.")

    selection_event = st.dataframe(
        browse_table,
        width="stretch",
        height=480,
        hide_index=True,
        key=JOBS_BROWSE_TABLE_KEY,
        on_select="rerun",
        selection_mode="multi-row",
        column_config={
            "company_name": st.column_config.TextColumn("Company", width="medium"),
            "title": st.column_config.TextColumn("Title", width="large"),
            "location": st.column_config.TextColumn("Location", width="small"),
            "tracking_status": st.column_config.TextColumn("Tracking", width="small"),
            "source_board": st.column_config.TextColumn("Source", width="small"),
            "keyword_score": st.column_config.NumberColumn("Keyword", format="%.2f"),
            "fit_score": st.column_config.NumberColumn("Fit", format="%.1f"),
            "date_found": st.column_config.TextColumn("Found", width="small"),
            "active": st.column_config.TextColumn("Active", width="small"),
            "url": st.column_config.LinkColumn("URL", width="medium"),
            "job_id": None,
        },
        column_order=[*BROWSE_COLUMNS, "job_id"],
    )

    selected_indices = _selection_rows(selection_event, JOBS_BROWSE_TABLE_KEY)
    selected_job_ids = _job_ids_for_indices(browse_table, selected_indices)
    _render_bulk_actions(browse_table, selected_job_ids)

    if not selected_job_ids:
        st.caption("Select one or more rows in the table above to preview and take action.")
        return

    if len(selected_job_ids) == 1:
        _render_single_job_detail(int(selected_job_ids[0]))
    else:
        _render_multi_job_summary(browse_table, selected_job_ids)


def _render_bulk_actions(browse_table: pd.DataFrame, selected_job_ids: list[int]) -> None:
    count = len(selected_job_ids)
    action_col1, action_col2, action_col3, action_col4, action_col5 = st.columns([1.2, 1.2, 1.2, 1, 1.5])

    with action_col1:
        if st.button(
            f"Add to tracking ({count})" if count else "Add to tracking",
            disabled=count == 0,
            type="primary",
            width="stretch",
            key="jobs_bulk_track",
        ):
            track_jobs(selected_job_ids)
            refresh_data()
            navigate_to_tracking()
            st.rerun()

    with action_col2:
        if st.button(
            f"Remove from tracking ({count})" if count else "Remove from tracking",
            disabled=count == 0,
            width="stretch",
            key="jobs_bulk_untrack",
        ):
            untrack_jobs(selected_job_ids)
            refresh_data()
            st.rerun()

    with action_col3:
        if st.button(
            "View full detail",
            disabled=count != 1,
            width="stretch",
            key="jobs_bulk_view_detail",
        ):
            select_job(selected_job_ids[0])
            st.rerun()

    with action_col4:
        if st.button("Clear selection", disabled=count == 0, width="stretch", key="jobs_clear_selection"):
            _clear_table_selection(JOBS_BROWSE_TABLE_KEY)
            st.rerun()

    with action_col5:
        st.caption(f"{count} selected · {len(browse_table)} shown")


def _render_single_job_detail(job_id: int) -> None:
    job = get_job_by_id(job_id)
    if job is None:
        st.warning("Selected job was not found.")
        return

    st.subheader("Job details")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Title:** {job.get('title', '—')}")
        st.markdown(f"**Company:** {job.get('company_name', '—')}")
        st.markdown(f"**Location:** {job.get('location') or '—'}")
        st.markdown(f"**Source board:** {job.get('source_board') or '—'}")
    with col2:
        fit_score = job.get("fit_score")
        fit_text = f"{float(fit_score):.1f}" if pd.notna(fit_score) else "Pending evaluation"
        st.markdown(f"**Fit score:** {fit_text}")
        keyword_score = job.get("keyword_score")
        if pd.notna(keyword_score):
            st.markdown(f"**Keyword score:** {float(keyword_score):.2f}")
        tracked = get_tracked_job(job_id)
        if tracked:
            st.markdown(f"**Tracking stage:** {STAGE_LABELS.get(tracked['stage'], tracked['stage'])}")

    url = str(job.get("url") or "").strip()
    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)
    with btn_col1:
        if tracked:
            if st.button("Remove from tracking", key=f"jobs_detail_untrack_{job_id}", width="stretch"):
                untrack_jobs([job_id])
                refresh_data()
                st.rerun()
        elif st.button(
            "Add to tracked jobs",
            key=f"jobs_detail_track_{job_id}",
            type="primary",
            width="stretch",
        ):
            track_jobs([job_id])
            refresh_data()
            navigate_to_tracking()
            st.rerun()
    with btn_col2:
        if st.button("View full detail", key=f"jobs_detail_open_{job_id}", width="stretch"):
            select_job(job_id)
            st.rerun()
    with btn_col3:
        if url:
            st.link_button("Open posting", url, width="stretch")
        else:
            st.button("Open posting", disabled=True, width="stretch")
    with btn_col4:
        if st.button("View company", key=f"jobs_detail_company_{job_id}", width="stretch"):
            select_company(str(job.get("company_name", "")))
            st.session_state.show_job_detail = False
            st.rerun()

    description = job.get("description")
    if description and str(description).strip():
        st.text_area(
            "Description",
            value=str(description),
            height=220,
            disabled=True,
            label_visibility="collapsed",
        )


def _render_multi_job_summary(browse_table: pd.DataFrame, selected_job_ids: list[int]) -> None:
    st.subheader(f"{len(selected_job_ids)} jobs selected")
    selected_rows = browse_table[browse_table["job_id"].isin(selected_job_ids)]
    summary = selected_rows[["company_name", "title", "location", "tracking_status"]].copy()
    st.dataframe(summary, width="stretch", hide_index=True)


def _build_browse_table(filtered: pd.DataFrame, stage_map: dict[int, str]) -> pd.DataFrame:
    table = filtered.copy()
    table["tracking_status"] = table["job_id"].apply(
        lambda job_id: STAGE_LABELS.get(stage_map.get(int(job_id), ""), "Not tracked")
        if int(job_id) in stage_map
        else "Not tracked"
    )
    if "active" in table.columns:
        table["active"] = table["active"].map(_format_active)

    columns = [column for column in [*BROWSE_COLUMNS, "job_id"] if column in table.columns]
    return table[columns].reset_index(drop=True)


def _selection_rows(selection_event: object | None, key: str) -> list[int]:
    if selection_event is not None and hasattr(selection_event, "selection"):
        selection = selection_event.selection
        if selection is not None and hasattr(selection, "rows"):
            return list(selection.rows or [])
    return _get_table_selection(key)


def _get_table_selection(key: str) -> list[int]:
    state = st.session_state.get(key)
    if state is None:
        return []
    if hasattr(state, "selection") and state.selection is not None:
        return list(state.selection.rows or [])
    if isinstance(state, dict):
        selection = state.get("selection", {})
        if isinstance(selection, dict):
            return list(selection.get("rows", []))
    return []


def _clear_table_selection(key: str) -> None:
    st.session_state[key] = {"selection": {"rows": [], "columns": [], "cells": []}}


def _job_ids_for_indices(table: pd.DataFrame, indices: list[int]) -> list[int]:
    if not indices or "job_id" not in table.columns:
        return []
    valid_indices = [index for index in indices if 0 <= index < len(table)]
    if not valid_indices:
        return []
    return [int(job_id) for job_id in table.iloc[valid_indices]["job_id"].tolist()]


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
        _clear_table_selection(JOBS_BROWSE_TABLE_KEY)

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
