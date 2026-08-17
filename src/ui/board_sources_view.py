"""Board and discovery source health view."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.jobs.board_health import (
    build_board_health_frame,
    build_board_health_summary,
    build_employer_ats_source_frame,
    build_other_source_rows,
    load_board_discovery_runs,
    parse_board_run_notes,
)
from src.ui.theme import inject_tracking_theme


HEALTH_ICONS = {
    "healthy": "🟢",
    "warning": "🟡",
    "error": "🔴",
    "disabled": "⚪",
    "stub": "⬜",
    "not_run": "🔵",
    "unknown": "⚫",
}

BOARD_DISPLAY_COLUMNS = (
    "health",
    "name",
    "source_id",
    "enabled",
    "phase",
    "priority",
    "scrape_mode",
    "adapter",
    "jobs_total",
    "jobs_active",
    "last_run_at",
    "last_raw_jobs",
    "health_label",
    "base_url",
)


@st.cache_data(show_spinner=False)
def _load_board_health_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    frame = build_board_health_frame()
    ats = build_employer_ats_source_frame()
    other = build_other_source_rows()
    summary = build_board_health_summary(frame)
    return frame, ats, other, summary


def render_board_sources_view() -> None:
    """Render configured job boards, job counts, and health status."""
    inject_tracking_theme()

    st.header("Board Sources")
    st.caption(
        "Configured job boards from `config/job_board_sources.yaml`, jobs stored per source, "
        "and health inferred from discovery runs and database counts."
    )

    try:
        frame, ats_sources, other_sources, summary = _load_board_health_data()
    except Exception as exc:
        st.error(f"Failed to load board source data: {exc}")
        return

    _render_summary_metrics(summary, ats_sources, other_sources)

    if frame.empty:
        st.warning("No boards configured.")
        return

    display = _prepare_display_frame(frame)
    filtered = _render_filters(display)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        _render_jobs_chart(filtered)
    with chart_col2:
        _render_health_chart(filtered)

    st.subheader("Configured boards")
    st.dataframe(
        filtered[[column for column in BOARD_DISPLAY_COLUMNS if column in filtered.columns]],
        width="stretch",
        hide_index=True,
        column_config={
            "health": st.column_config.TextColumn("Status", width="small"),
            "base_url": st.column_config.LinkColumn("Site"),
            "enabled": st.column_config.CheckboxColumn("Enabled", disabled=True),
            "jobs_total": st.column_config.NumberColumn("Jobs", format="%d"),
            "jobs_active": st.column_config.NumberColumn("Active", format="%d"),
            "last_raw_jobs": st.column_config.NumberColumn("Last run jobs", format="%d"),
        },
    )

    st.subheader("Employer ATS sources")
    st.caption(
        "Employer-specific Greenhouse, Lever, Ashby, and Workday boards discovered "
        "from company career pages and known posting URLs."
    )
    if ats_sources.empty:
        st.info(
            "No employer ATS sources registered yet. Run "
            "`python -m src.jobs.run_employer_ats_discovery --dry-run` to preview."
        )
    else:
        st.dataframe(ats_sources, width="stretch", hide_index=True)

    if not other_sources.empty:
        st.subheader("Other job sources")
        st.dataframe(other_sources, width="stretch", hide_index=True)

    _render_recent_runs()


def _render_summary_metrics(
    summary: dict[str, int], ats_sources: pd.DataFrame, other_sources: pd.DataFrame
) -> None:
    other_jobs = int(other_sources["jobs_total"].sum()) if not other_sources.empty else 0
    ats_employers = int(ats_sources["employers"].sum()) if not ats_sources.empty else 0
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Boards configured", summary["total_boards"])
    col2.metric("Enabled", summary["enabled_boards"])
    col3.metric("Healthy", summary["healthy_boards"])
    col4.metric("Warning / error", summary["warning_boards"] + summary["error_boards"])
    col5.metric("Board jobs", summary["total_board_jobs"])
    col6.metric("ATS employers / other jobs", f"{ats_employers} / {other_jobs}")


def _prepare_display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    display["health"] = [
        f"{HEALTH_ICONS.get(str(status), '⚫')} {label}"
        for status, label in zip(display["health_status"], display["health_label"], strict=False)
    ]
    display["enabled"] = display["enabled"].astype(bool)
    return display.sort_values(
        ["enabled", "health_status", "jobs_total"],
        ascending=[False, True, False],
    )


def _render_filters(display: pd.DataFrame) -> pd.DataFrame:
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        show_disabled = st.checkbox("Show disabled boards", value=True, key="board_show_disabled")
    with filter_col2:
        health_options = sorted(display["health_label"].unique().tolist())
        selected_health = st.multiselect(
            "Health status",
            options=health_options,
            default=health_options,
            key="board_health_filter",
        )
    with filter_col3:
        phase_options = sorted(display["phase"].unique().tolist())
        selected_phases = st.multiselect(
            "Phase",
            options=phase_options,
            default=phase_options,
            key="board_phase_filter",
        )

    filtered = display.copy()
    if not show_disabled:
        filtered = filtered[filtered["enabled"]]
    if selected_health:
        filtered = filtered[filtered["health_label"].isin(selected_health)]
    if selected_phases:
        filtered = filtered[filtered["phase"].isin(selected_phases)]
    return filtered


def _render_jobs_chart(frame: pd.DataFrame) -> None:
    chart_data = frame[frame["jobs_total"] > 0][["name", "jobs_total"]].sort_values(
        "jobs_total", ascending=True
    )
    if chart_data.empty:
        st.info("No board jobs stored yet.")
        return
    fig = px.bar(
        chart_data,
        x="jobs_total",
        y="name",
        orientation="h",
        title="Jobs stored by board",
        labels={"jobs_total": "Jobs", "name": "Board"},
    )
    fig.update_layout(height=max(280, len(chart_data) * 24))
    st.plotly_chart(fig, width="stretch")


def _render_health_chart(frame: pd.DataFrame) -> None:
    enabled = frame[frame["enabled"]]
    if enabled.empty:
        st.info("No enabled boards.")
        return
    counts = enabled["health_label"].value_counts().reset_index()
    counts.columns = ["health_label", "count"]
    fig = px.pie(counts, names="health_label", values="count", title="Enabled board health")
    st.plotly_chart(fig, width="stretch")


def _render_recent_runs() -> None:
    runs = load_board_discovery_runs(limit=10)
    if not runs:
        st.subheader("Recent board discovery runs")
        st.caption("No board discovery runs logged yet. Run `python -m src.jobs.run_board_discovery`.")
        return

    st.subheader("Recent board discovery runs")
    rows: list[dict[str, object]] = []
    for run in runs:
        payload = parse_board_run_notes(str(run.get("notes") or ""))
        rows.append(
            {
                "completed_at": run.get("completed_at") or run.get("started_at"),
                "run_id": payload.get("run_id", ""),
                "boards_checked": payload.get("boards_checked", run.get("companies_checked")),
                "raw_jobs": payload.get("raw_jobs_found", ""),
                "filtered_jobs": payload.get("jobs_after_filter", ""),
                "inserted": payload.get("inserted", ""),
                "dry_run": payload.get("dry_run", False),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
