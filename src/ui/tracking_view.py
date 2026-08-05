"""Job application tracking view."""

from __future__ import annotations

import streamlit as st

from src.database.tracked_jobs import (
    STAGE_LABELS,
    TERMINAL_STAGES,
    TRACKING_STAGES,
    get_tracked_job,
    list_tracked_jobs,
    track_job,
    untrack_job,
    update_tracked_notes,
    update_tracked_stage,
)
from src.ui.actions import refresh_data
from src.ui.data_loader import get_job_by_id
from src.ui.job_detail_view import render_job_detail_view
from src.ui.session_utils import select_job, select_tracking_job
from src.ui.theme import inject_tracking_theme, stage_badge_html, tracking_card_html


ACTIVE_PIPELINE_STAGES = ("tracked", "applying", "applied", "interviewing", "accepted")
ARCHIVE_STAGES = ("rejected", "withdrawn")


def render_tracking_view() -> None:
    """Render the tracked jobs pipeline and sidebar-selected job preview."""
    inject_tracking_theme()

    if st.session_state.get("show_job_detail") and st.session_state.get("selected_job_id"):
        render_job_detail_view()
        return

    st.markdown(
        '<div class="tracking-header"><h2 style="margin:0;color:#115e59;">'
        "Application Tracking</h2>"
        "<p style='margin:0.35rem 0 0;color:#334155;'>"
        "Your application pipeline. Browse jobs on the Jobs tab, add roles here, "
        "and move them from tracked through applied to accepted."
        "</p></div>",
        unsafe_allow_html=True,
    )

    selected_job_id = st.session_state.get("tracking_selected_job_id")
    if selected_job_id:
        _render_job_preview_panel(selected_job_id)

    tracked = list_tracked_jobs()
    if not tracked:
        st.info(
            "No tracked jobs yet. Open the **Jobs** tab to browse postings, "
            "then click **Add to tracked jobs** on any role you want to pursue."
        )
        return

    _render_pipeline_metrics(tracked)
    _render_pipeline_board(tracked)


def _render_job_preview_panel(job_id: str) -> None:
    job = get_job_by_id(job_id)
    if job is None:
        st.warning("Selected job was not found.")
        return

    tracked = get_tracked_job(int(job_id))
    title = str(job.get("title", "Untitled"))
    company = str(job.get("company_name", ""))
    location = str(job.get("location") or "")

    st.markdown(
        tracking_card_html(
            title=title,
            company=company,
            stage=str(tracked.get("stage", "tracked")) if tracked else "tracked",
            location=location,
        ),
        unsafe_allow_html=True,
    )

    action_col1, action_col2, action_col3, action_col4 = st.columns([1, 1, 1, 1])
    with action_col1:
        if tracked:
            if st.button("Remove from tracking", key=f"untrack_{job_id}", width="stretch"):
                untrack_job(int(job_id))
                refresh_data()
                st.session_state.tracking_selected_job_id = None
                st.rerun()
        else:
            if st.button(
                "Add to tracked jobs",
                key=f"track_{job_id}",
                type="primary",
                width="stretch",
            ):
                track_job(int(job_id))
                refresh_data()
                st.rerun()

    with action_col2:
        url = str(job.get("url") or "").strip()
        if url:
            st.link_button("Open posting", url, width="stretch")
        else:
            st.button("Open posting", disabled=True, width="stretch")

    with action_col3:
        if st.button("Open full job detail", key=f"detail_{job_id}", width="stretch"):
            select_job(job_id)
            st.rerun()

    with action_col4:
        if st.button("Close", key=f"close_{job_id}", width="stretch"):
            st.session_state.tracking_selected_job_id = None
            st.rerun()

    if tracked:
        stage_options = [stage for stage, _ in TRACKING_STAGES]
        current_stage = str(tracked.get("stage", "tracked"))
        stage_index = stage_options.index(current_stage) if current_stage in stage_options else 0
        new_stage = st.selectbox(
            "Pipeline stage",
            options=stage_options,
            index=stage_index,
            format_func=lambda value: STAGE_LABELS.get(value, value.title()),
            key=f"preview_stage_{job_id}",
        )
        if new_stage != current_stage:
            update_tracked_stage(int(job_id), new_stage)
            refresh_data()
            st.rerun()

        notes = st.text_area(
            "Notes",
            value=str(tracked.get("notes") or ""),
            key=f"preview_notes_{job_id}",
            height=90,
        )
        if st.button("Save notes", key=f"save_notes_{job_id}"):
            update_tracked_notes(int(job_id), notes)
            refresh_data()
            st.success("Notes saved.")
            st.rerun()

    st.divider()


def _render_pipeline_metrics(tracked: list[dict]) -> None:
    active_count = sum(1 for row in tracked if row.get("stage") not in TERMINAL_STAGES)
    applied_count = sum(1 for row in tracked if row.get("stage") in {"applied", "interviewing", "accepted"})
    accepted_count = sum(1 for row in tracked if row.get("stage") == "accepted")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tracked total", len(tracked))
    col2.metric("Active pipeline", active_count)
    col3.metric("Applied+", applied_count)
    col4.metric("Accepted", accepted_count)


def _render_pipeline_board(tracked: list[dict]) -> None:
    st.subheader("Pipeline board")

    columns = st.columns(len(ACTIVE_PIPELINE_STAGES))
    for column, stage in zip(columns, ACTIVE_PIPELINE_STAGES, strict=True):
        with column:
            stage_rows = [row for row in tracked if row.get("stage") == stage]
            st.markdown(
                f'<div class="tracking-column-header">{STAGE_LABELS[stage]} ({len(stage_rows)})</div>',
                unsafe_allow_html=True,
            )
            if not stage_rows:
                st.caption("No jobs")
                continue

            for row in stage_rows:
                job_id = str(row["job_id"])
                title = str(row.get("title", "Untitled"))
                company = str(row.get("company_name", ""))
                st.markdown(
                    tracking_card_html(
                        title=title,
                        company=company,
                        stage=stage,
                        location=str(row.get("location") or ""),
                    ),
                    unsafe_allow_html=True,
                )
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("Open", key=f"open_{stage}_{job_id}", width="stretch"):
                        select_tracking_job(job_id)
                        st.rerun()
                with btn_col2:
                    next_stage = _next_stage(stage)
                    if next_stage and st.button(
                        f"→ {STAGE_LABELS[next_stage]}",
                        key=f"advance_{stage}_{job_id}",
                        width="stretch",
                    ):
                        update_tracked_stage(int(job_id), next_stage)
                        refresh_data()
                        st.rerun()

    archive_rows = [row for row in tracked if row.get("stage") in ARCHIVE_STAGES]
    if archive_rows:
        with st.expander(f"Archived ({len(archive_rows)})", expanded=False):
            for row in archive_rows:
                job_id = str(row["job_id"])
                stage = str(row.get("stage", ""))
                st.markdown(
                    f"{stage_badge_html(stage)} **{row.get('title', '')}** — {row.get('company_name', '')}",
                    unsafe_allow_html=True,
                )
                restore_col1, restore_col2 = st.columns([1, 1])
                with restore_col1:
                    if st.button("Reopen as tracked", key=f"restore_{job_id}", width="stretch"):
                        update_tracked_stage(int(job_id), "tracked")
                        refresh_data()
                        st.rerun()
                with restore_col2:
                    if st.button("Remove", key=f"archive_remove_{job_id}", width="stretch"):
                        untrack_job(int(job_id))
                        refresh_data()
                        st.rerun()


def _next_stage(stage: str) -> str | None:
    order = list(ACTIVE_PIPELINE_STAGES)
    if stage not in order:
        return None
    index = order.index(stage)
    if index >= len(order) - 1:
        return None
    return order[index + 1]
