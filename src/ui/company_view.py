"""Companies view with filters, selection, and pipeline actions."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.database.import_inventory import get_inventory_path
from src.ui.actions import (
    CareerDiscoveryResult,
    JobDiscoveryActionResult,
    refresh_data,
    run_career_page_discovery,
    run_job_discovery_action,
)
from src.ui.data_loader import COMPANY_TABLE_COLUMNS, build_company_dashboard_frame, load_run_history
from src.ui.session_utils import select_company
from src.ui.status_utils import CAREER_FILTER_LABELS, JOB_FILTER_LABELS

COMPANY_TABLE_KEY = "company_selection_table"


def render_company_view() -> None:
    """Render the interactive companies control panel."""
    if st.session_state.get("show_company_detail") and st.session_state.get("selected_company"):
        from src.ui.company_detail_view import render_company_detail_view

        render_company_detail_view()
        return

    st.header("Companies")
    st.caption("Browse the company inventory, run discovery pipelines, and review status.")

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

    filtered, sorted_frame = _render_filter_form(frame)

    st.subheader("Company list")
    st.caption("Check companies in the list below, then run an action.")

    select_col1, select_col2, select_col3 = st.columns([1, 1, 4])
    with select_col1:
        if st.button("Select all shown", width="stretch"):
            _set_all_checkbox_state(sorted_frame, selected=True)
            st.rerun()
    with select_col2:
        if st.button("Clear selection", width="stretch"):
            _set_all_checkbox_state(sorted_frame, selected=False)
            st.rerun()

    editable_table = _build_selectable_table(sorted_frame)
    edited_table = st.data_editor(
        editable_table,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", default=False, width="small"),
            "company_name": st.column_config.TextColumn("Company", disabled=True),
            "industry": st.column_config.TextColumn("Industry", disabled=True),
            "location": st.column_config.TextColumn("Location", disabled=True),
            "priority": st.column_config.TextColumn("Priority", disabled=True),
            "hiring_status": st.column_config.TextColumn("Hiring Status", disabled=True),
            "career_page_status": st.column_config.TextColumn("Career Page Status", disabled=True),
            "job_search_status": st.column_config.TextColumn("Job Search Status", disabled=True),
            "jobs_found": st.column_config.NumberColumn("Jobs Found", format="%d", disabled=True),
            "last_checked": st.column_config.TextColumn("Last Checked", disabled=True),
            "career_page": st.column_config.LinkColumn("Career Page", disabled=True),
        },
        disabled=[column for column in editable_table.columns if column != "Select"],
        key=COMPANY_TABLE_KEY,
    )

    action_targets = _selected_company_names(edited_table)
    with select_col3:
        st.caption(f"{len(action_targets)} companies selected")

    company_names = sorted_frame["company_name"].tolist()
    if company_names:
        profile_col1, profile_col2 = st.columns([3, 1])
        with profile_col1:
            profile_company = st.selectbox(
                "Open company profile",
                options=company_names,
                index=_profile_select_index(company_names),
                key="open_company_profile_select",
            )
        with profile_col2:
            st.write("")
            st.write("")
            if st.button("View Company", width="stretch", key="view_company_profile_button"):
                select_company(profile_company)
                st.rerun()

    _render_action_buttons(sorted_frame, action_targets)
    _render_last_result_summary()

    st.metric("Companies shown", len(sorted_frame))
    _render_run_history()


def _profile_select_index(company_names: list[str]) -> int:
    current = st.session_state.get("open_company_profile_select")
    if current in company_names:
        return company_names.index(current)
    return 0


def _build_selectable_table(sorted_frame: pd.DataFrame) -> pd.DataFrame:
    """Build table input for data_editor, preserving checkbox state from the widget key."""
    table = sorted_frame.copy()
    table.insert(0, "Select", False)
    table = table[["Select", *COMPANY_TABLE_COLUMNS]]

    existing = st.session_state.get(COMPANY_TABLE_KEY)
    if not isinstance(existing, pd.DataFrame) or "company_name" not in existing.columns:
        return table

    prior = existing.set_index("company_name")["Select"].to_dict()
    table["Select"] = table["company_name"].map(lambda name: bool(prior.get(name, False)))
    return table


def _set_all_checkbox_state(sorted_frame: pd.DataFrame, *, selected: bool) -> None:
    table = sorted_frame.copy()
    table.insert(0, "Select", selected)
    table = table[["Select", *COMPANY_TABLE_COLUMNS]]
    st.session_state[COMPANY_TABLE_KEY] = table


def _selected_company_names(edited_table: pd.DataFrame) -> list[str]:
    selected = edited_table[edited_table["Select"] == True]  # noqa: E712
    return [str(name) for name in selected["company_name"].tolist()]


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
            "sort_label": "Company",
            "ascending": True,
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

        sort_col1, sort_col2, sort_col3 = st.columns([3, 1, 1])
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
            st.write("")
            st.write("")
            apply_filters = st.form_submit_button("Apply filters", width="stretch")

    if apply_filters:
        st.session_state.company_filter_defaults = {
            "priorities": selected_priorities,
            "industries": selected_industries,
            "locations": selected_locations,
            "career_statuses": selected_career,
            "job_statuses": selected_job,
            "sort_label": sort_label,
            "ascending": ascending,
        }
        st.session_state.pop(COMPANY_TABLE_KEY, None)

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
        "Company": "company_name",
        "Priority": "priority",
        "Jobs Found": "jobs_found",
    }


def _render_action_buttons(sorted_frame: pd.DataFrame, action_targets: list[str]) -> None:
    force_recheck = st.checkbox(
        "Force re-check existing career pages",
        value=False,
        help="When enabled, career page discovery overwrites existing career_page values.",
        key="force_recheck_career_pages",
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        find_careers = st.button("Find Career Pages", width="stretch", key="find_career_pages_button")
    with col2:
        run_jobs = st.button("Run Job Discovery", width="stretch", key="run_job_discovery_button")
    with col3:
        refresh = st.button("Refresh Dashboard", width="stretch", key="refresh_dashboard_button")
    with col4:
        st.download_button(
            label="Export Filtered Companies",
            data=sorted_frame.to_csv(index=False).encode("utf-8"),
            file_name="filtered_companies.csv",
            mime="text/csv",
            width="stretch",
            key="export_filtered_companies_button",
        )

    if refresh:
        refresh_data()
        st.session_state.pop("last_career_result", None)
        st.session_state.pop("last_job_result", None)
        st.session_state.pop("global_search_results", None)
        st.success("Dashboard data refreshed.")
        st.rerun()

    if find_careers:
        if not action_targets:
            st.error("Select at least one company in the list above.")
            return
        _run_career_discovery(action_targets, force=force_recheck)

    if run_jobs:
        if not action_targets:
            st.error("Select at least one company in the list above.")
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
        j2.metric("Jobs found", job_result.jobs_found)
        j3.metric("Jobs inserted", job_result.jobs_inserted)
        j4.metric("Duplicates skipped", job_result.duplicates_skipped)
        j5.metric("Errors", job_result.errors)


def _render_run_history() -> None:
    runs = load_run_history()
    st.subheader("Run history")
    if runs.empty:
        st.info("No pipeline runs recorded yet.")
        return

    display = runs[["run_type", "started_at", "companies_checked"]].copy()
    display = display.rename(
        columns={
            "run_type": "Run type",
            "started_at": "Time",
            "companies_checked": "Companies checked",
        }
    )
    st.dataframe(display, width="stretch", hide_index=True)


def _sorted_unique(series: pd.Series) -> list[str]:
    values = {
        str(value).strip()
        for value in series.fillna("").tolist()
        if str(value).strip()
    }
    return sorted(values)
