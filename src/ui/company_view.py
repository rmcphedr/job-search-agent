"""Companies view with filters, selection, pipeline actions, and detail panel."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.database.import_inventory import get_inventory_path
from src.orchestration.run_loader import load_calibration_summary, load_latest_run_manifest, load_run_summaries
from src.ui.actions import (
    CareerDiscoveryResult,
    JobDiscoveryActionResult,
    refresh_data,
    run_career_page_discovery,
    run_job_discovery_action,
)
from src.ui.company_detail_view import render_company_detail_panel
from src.ui.data_loader import COMPANY_LIST_COLUMNS, build_company_dashboard_frame, load_run_history
from src.ui.status_utils import CAREER_FILTER_LABELS, JOB_FILTER_LABELS

COMPANY_BROWSE_TABLE_KEY = "company_browse_table"


def render_company_view() -> None:
    """Render the interactive companies control panel."""
    st.header("Companies")
    st.caption(
        "Browse the company inventory, review fit evaluations, and run discovery pipelines. "
        "Click a row to preview details in the panel."
    )

    inventory_path = get_inventory_path()
    try:
        frame = build_company_dashboard_frame()
    except Exception as exc:
        st.error(f"Failed to load company data: {exc}")
        return

    if frame.empty:
        if not inventory_path.exists():
            st.warning(
                f"Company inventory not found at `{inventory_path}`. "
                "Run directory discovery or add `data/company_inventory.csv`."
            )
        else:
            st.warning("Company inventory is empty.")
        return

    _render_discovery_run_summary()

    filtered, sorted_frame = _render_filter_form(frame)
    browse_table = _prepare_browse_table(sorted_frame)

    table_col, panel_col = st.columns([1.55, 1])

    with table_col:
        st.metric("Companies shown", len(browse_table))
        st.caption("Click rows to select. Shift+Click extends selection; Cmd/Ctrl+Click toggles rows.")

        selection_event = st.dataframe(
            browse_table,
            width="stretch",
            height=520,
            hide_index=True,
            key=COMPANY_BROWSE_TABLE_KEY,
            on_select="rerun",
            selection_mode="multi-row",
            column_config={
                "company_name": st.column_config.TextColumn("Company", width="medium"),
                "industry": st.column_config.TextColumn("Industry", width="medium"),
                "fit_score": st.column_config.NumberColumn("Fit", format="%.1f"),
                "priority": st.column_config.TextColumn("Priority", width="small"),
                "hiring_status": st.column_config.TextColumn("Hiring", width="small"),
                "career_page_status": st.column_config.TextColumn("Career page", width="small"),
                "job_search_status": st.column_config.TextColumn("Job search", width="small"),
                "jobs_found": st.column_config.NumberColumn("Jobs", format="%d"),
                "company_id": None,
            },
            column_order=[*COMPANY_LIST_COLUMNS, "company_id"],
        )

        selected_indices = _selection_rows(selection_event, COMPANY_BROWSE_TABLE_KEY)
        selected_names = _company_names_for_indices(browse_table, selected_indices)
        _render_action_buttons(browse_table, selected_names)
        _render_last_result_summary()
        _render_run_history()

    with panel_col:
        st.subheader("Company preview")
        if len(selected_names) == 1:
            render_company_detail_panel(selected_names[0])
        elif len(selected_names) > 1:
            st.info(f"{len(selected_names)} companies selected.")
            summary = browse_table.iloc[selected_indices][["company_name", "industry", "fit_score", "jobs_found"]]
            st.dataframe(summary, width="stretch", hide_index=True)
        else:
            preselected = st.session_state.get("selected_company")
            if preselected and preselected in browse_table["company_name"].tolist():
                render_company_detail_panel(preselected)
            else:
                st.caption("Select a company in the table to preview fit breakdown and details.")


def _prepare_browse_table(sorted_frame: pd.DataFrame) -> pd.DataFrame:
    table = sorted_frame.copy()
    if "fit_score" in table.columns:
        table["fit_score"] = pd.to_numeric(table["fit_score"], errors="coerce")
    columns = [column for column in [*COMPANY_LIST_COLUMNS, "company_id"] if column in table.columns]
    return table[columns].reset_index(drop=True)


def _render_discovery_run_summary() -> None:
    latest_run = load_latest_run_manifest()
    if latest_run is None:
        return

    with st.expander("Latest discovery run", expanded=False):
        counts = latest_run.counts
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Run ID", latest_run.run_id)
        c2.metric("Merged candidates", counts.candidates_merged)
        c3.metric("Evaluations merged", counts.evaluations_merged)
        c4.metric("Duplicates skipped", counts.candidates_duplicate)
        c5.metric("Status", latest_run.status)

        if latest_run.request:
            st.json(latest_run.request)

        calibration = load_calibration_summary(latest_run.run_id)
        if calibration:
            st.markdown("**Calibration status**")
            st.json(calibration)


def _render_filter_form(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Render filters inside a form so they do not rerun the page on every click."""
    defaults = st.session_state.setdefault(
        "company_filter_defaults",
        {
            "priorities": [],
            "industries": [],
            "locations": [],
            "career_statuses": [],
            "job_statuses": [],
            "min_fit_score": 0.0,
            "include_unevaluated": True,
            "sort_label": "Fit score",
            "ascending": False,
        },
    )

    with st.form("company_filters_form", clear_on_submit=False):
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            priority_values = _sorted_unique(frame["priority"])
            selected_priorities = st.multiselect(
                "Priority",
                priority_values,
                default=defaults["priorities"],
                key="filter_priority",
            )
        with col2:
            industry_values = _sorted_unique(frame["industry"])
            selected_industries = st.multiselect(
                "Industry",
                industry_values,
                default=defaults["industries"],
                key="filter_industry",
            )
        with col3:
            location_values = _sorted_unique(frame["location"])
            selected_locations = st.multiselect(
                "Location",
                location_values,
                default=defaults["locations"],
                key="filter_location",
            )
        with col4:
            career_values = list(CAREER_FILTER_LABELS.values())
            selected_career = st.multiselect(
                "Career Status",
                career_values,
                default=defaults["career_statuses"],
                key="filter_career_status",
            )
        with col5:
            job_values = list(JOB_FILTER_LABELS.values())
            selected_job = st.multiselect(
                "Job Status",
                job_values,
                default=defaults["job_statuses"],
                key="filter_job_status",
            )

        sort_col1, sort_col2, sort_col3, sort_col4 = st.columns([2, 1, 1, 1])
        with sort_col1:
            sort_options = list(_sort_options().keys())
            sort_label = st.selectbox(
                "Sort by",
                options=sort_options,
                index=sort_options.index(defaults["sort_label"])
                if defaults["sort_label"] in sort_options
                else 0,
                key="filter_sort_by",
            )
        with sort_col2:
            ascending = st.checkbox("Ascending", value=defaults["ascending"], key="filter_ascending")
        with sort_col3:
            min_fit_score = st.slider(
                "Min fit score",
                min_value=0.0,
                max_value=10.0,
                value=float(defaults.get("min_fit_score", 0.0)),
                step=0.5,
                key="filter_min_fit_score",
            )
        with sort_col4:
            include_unevaluated = st.checkbox(
                "Include unevaluated",
                value=defaults.get("include_unevaluated", True),
                key="filter_include_unevaluated",
            )

        apply_filters = st.form_submit_button("Apply filters", width="stretch")

    if apply_filters:
        st.session_state.company_filter_defaults = {
            "priorities": selected_priorities,
            "industries": selected_industries,
            "locations": selected_locations,
            "career_statuses": selected_career,
            "job_statuses": selected_job,
            "min_fit_score": min_fit_score,
            "include_unevaluated": include_unevaluated,
            "sort_label": sort_label,
            "ascending": ascending,
        }
        _clear_table_selection(COMPANY_BROWSE_TABLE_KEY)

    active = st.session_state.company_filter_defaults
    filtered = frame.copy()
    if active["priorities"]:
        filtered = filtered[filtered["priority"].isin(active["priorities"])]
    if active["industries"]:
        filtered = filtered[filtered["industry"].isin(active["industries"])]
    if active["locations"]:
        filtered = filtered[filtered["location"].isin(active["locations"])]
    if active["career_statuses"]:
        allowed = {
            label for label, value in CAREER_FILTER_LABELS.items() if value in active["career_statuses"]
        }
        filtered = filtered[filtered["career_page_status"].isin(allowed)]
    if active["job_statuses"]:
        allowed = {
            label for label, value in JOB_FILTER_LABELS.items() if value in active["job_statuses"]
        }
        filtered = filtered[filtered["job_search_status"].isin(allowed)]

    if "fit_score" in filtered.columns:
        filtered["fit_score"] = pd.to_numeric(filtered["fit_score"], errors="coerce")
        min_score = float(active.get("min_fit_score", 0.0))
        if active.get("include_unevaluated", True):
            filtered = filtered[filtered["fit_score"].isna() | (filtered["fit_score"] >= min_score)]
        else:
            filtered = filtered[filtered["fit_score"].notna() & (filtered["fit_score"] >= min_score)]

    sort_column = _sort_options()[active["sort_label"]]
    sorted_frame = filtered.sort_values(
        by=sort_column,
        ascending=active["ascending"],
        kind="stable",
        na_position="last",
    )
    if sort_column == "jobs_found":
        sorted_frame["jobs_found"] = (
            pd.to_numeric(sorted_frame["jobs_found"], errors="coerce").fillna(0).astype(int)
        )
    return filtered, sorted_frame.reset_index(drop=True)


def _sort_options() -> dict[str, str]:
    return {
        "Fit score": "fit_score",
        "Company": "company_name",
        "Priority": "priority",
        "Jobs Found": "jobs_found",
    }


def _render_action_buttons(browse_table: pd.DataFrame, action_targets: list[str]) -> None:
    force_recheck = st.checkbox(
        "Force re-check existing career pages",
        value=False,
        help="When enabled, career page discovery overwrites existing career_page values.",
        key="force_recheck_career_pages",
    )

    count = len(action_targets)
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1.2])
    with col1:
        find_careers = st.button("Find Career Pages", width="stretch", key="find_career_pages_button")
    with col2:
        run_jobs = st.button("Run Job Discovery", width="stretch", key="run_job_discovery_button")
    with col3:
        refresh = st.button("Refresh Dashboard", width="stretch", key="refresh_dashboard_button")
    with col4:
        st.download_button(
            label="Export Filtered",
            data=browse_table.drop(columns=["company_id"], errors="ignore").to_csv(index=False).encode("utf-8"),
            file_name="filtered_companies.csv",
            mime="text/csv",
            width="stretch",
            key="export_filtered_companies_button",
        )
    with col5:
        if st.button("Clear selection", disabled=count == 0, width="stretch", key="companies_clear_selection"):
            _clear_table_selection(COMPANY_BROWSE_TABLE_KEY)
            st.rerun()
        st.caption(f"{count} selected")

    if refresh:
        refresh_data()
        st.session_state.pop("last_career_result", None)
        st.session_state.pop("last_job_result", None)
        st.session_state.pop("global_search_results", None)
        st.success("Dashboard data refreshed.")
        st.rerun()

    if find_careers:
        if not action_targets:
            st.error("Select at least one company in the table above.")
            return
        _run_career_discovery(action_targets, force=force_recheck)

    if run_jobs:
        if not action_targets:
            st.error("Select at least one company in the table above.")
            return
        _run_job_discovery(action_targets)


def _run_career_discovery(selected_companies: list[str], *, force: bool) -> None:
    progress = st.progress(0.0)
    status = st.empty()

    def update_progress(current: int, total: int, message: str) -> None:
        progress.progress(current / total if total else 1.0)
        status.text(message)

    try:
        result = run_career_page_discovery(
            selected_companies,
            force=force,
            sleep_seconds=1.0,
            progress_callback=update_progress,
        )
    except Exception as exc:
        st.error(f"Career page discovery failed: {exc}")
        return
    finally:
        progress.empty()
        status.empty()

    st.session_state["last_career_result"] = result
    refresh_data()
    st.rerun()


def _run_job_discovery(selected_companies: list[str]) -> None:
    progress = st.progress(0.0)
    status = st.empty()

    def update_progress(current: int, total: int, message: str) -> None:
        progress.progress(current / total if total else 1.0)
        status.text(message)

    try:
        result = run_job_discovery_action(
            selected_companies,
            sleep_seconds=1.0,
            progress_callback=update_progress,
        )
    except Exception as exc:
        st.error(f"Job discovery failed: {exc}")
        return
    finally:
        progress.empty()
        status.empty()

    st.session_state["last_job_result"] = result
    refresh_data()
    st.rerun()


def _render_last_result_summary() -> None:
    career_result: CareerDiscoveryResult | None = st.session_state.get("last_career_result")
    job_result: JobDiscoveryActionResult | None = st.session_state.get("last_job_result")

    if career_result is not None:
        st.subheader("Career page discovery results")
        if career_result.error_message:
            st.error(career_result.error_message)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Companies checked", career_result.companies_checked)
        c2.metric("Career pages found", career_result.career_pages_found)
        c3.metric("Career pages not found", career_result.career_pages_not_found)
        c4.metric("Errors", career_result.errors)
        if career_result.skipped:
            st.info(
                f"{career_result.skipped} companies skipped (already checked). "
                "Enable force re-check to overwrite."
            )

    if job_result is not None:
        st.subheader("Job discovery results")
        if job_result.error_message:
            st.error(job_result.error_message)
        j1, j2, j3, j4, j5 = st.columns(5)
        j1.metric("Companies checked", job_result.companies_checked)
        j2.metric("Jobs saved", job_result.jobs_found)
        j3.metric("Jobs inserted", job_result.jobs_inserted)
        j4.metric("LLM triaged", job_result.triaged_jobs)
        j5.metric("LLM fit scored", job_result.llm_fit_scored)
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Raw jobs", job_result.raw_jobs_found)
        f2.metric("Pre-screened", job_result.prescreened_jobs)
        f3.metric("Enriched", job_result.enriched_jobs)
        f4.metric("Duplicates skipped", job_result.duplicates_skipped)
        if job_result.errors:
            st.warning(f"{job_result.errors} companies had errors during job discovery.")


def _render_run_history() -> None:
    runs = load_run_history()
    summaries = load_run_summaries(limit=5)
    if runs.empty and not summaries:
        return

    with st.expander("Run history", expanded=False):
        if not runs.empty:
            display = runs[["run_type", "started_at", "companies_checked"]].copy()
            display = display.rename(
                columns={
                    "run_type": "Run type",
                    "started_at": "Time",
                    "companies_checked": "Companies checked",
                }
            )
            st.dataframe(display, width="stretch", hide_index=True)

        if summaries:
            st.markdown("**Recent Hermes discovery runs**")
            frame = pd.DataFrame(summaries)
            if not frame.empty:
                st.dataframe(frame[["run_id", "status", "started_at", "counts"]], width="stretch", hide_index=True)


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


def _company_names_for_indices(table: pd.DataFrame, indices: list[int]) -> list[str]:
    if not indices or "company_name" not in table.columns:
        return []
    valid_indices = [index for index in indices if 0 <= index < len(table)]
    if not valid_indices:
        return []
    return [str(name) for name in table.iloc[valid_indices]["company_name"].tolist()]


def _sorted_unique(series: pd.Series) -> list[str]:
    values = {
        str(value).strip()
        for value in series.fillna("").tolist()
        if str(value).strip()
    }
    return sorted(values)
