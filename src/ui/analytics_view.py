"""Analytics view for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.database.tracked_jobs import (
    STAGE_LABELS,
    list_application_stage_history,
    list_tracked_jobs,
)
from src.ui.data_loader import load_analytics_data
from src.ui.job_detail_view import render_job_detail_view
from src.ui.session_utils import select_job
from src.ui.theme import STAGE_COLORS, TEAL_PRIMARY


def render_analytics_view() -> None:
    """Render portfolio analytics and top opportunities."""
    if st.session_state.get("show_job_detail") and st.session_state.get("selected_job_id"):
        render_job_detail_view()
        return

    st.header("Analytics")
    st.caption("Overview of companies, career pages, jobs, and top opportunities.")

    try:
        data = load_analytics_data()
    except Exception as exc:
        st.error(f"Failed to load analytics: {exc}")
        return

    overview_tab, applications_tab = st.tabs(["Portfolio overview", "Applied jobs flow"])
    with overview_tab:
        _render_portfolio_overview(data)
    with applications_tab:
        _render_applied_jobs_flow()


def _render_portfolio_overview(data: dict) -> None:
    """Render the original company and opportunity analytics."""
    companies = data["companies"]
    jobs = data["jobs"]
    summary = data["summary"]

    if companies.empty:
        st.warning("No company data available for analytics.")
        return

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total companies", summary["total_companies"])
    m2.metric("With career pages", summary["companies_with_career_pages"])
    m3.metric("Missing career pages", summary["companies_missing_career_pages"])
    m4.metric("Companies with jobs", summary["companies_with_jobs"])
    m5.metric("Active jobs", summary["total_active_jobs"])
    m6.metric("Avg jobs / company", f"{summary['avg_jobs_per_company']:.2f}")

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        _render_bar_chart(companies, "industry", "Jobs By Industry", jobs)
        _render_status_chart(companies, "career_page_status", "Career Page Status Breakdown")
    with chart_col2:
        _render_bar_chart(jobs if not jobs.empty else companies, "location", "Jobs By Location", jobs)
        _render_status_chart(companies, "job_search_status", "Job Search Status Breakdown")

    priority_counts = (
        companies["priority"].fillna("Unknown").value_counts().reset_index()
        if "priority" in companies.columns
        else pd.DataFrame()
    )
    if not priority_counts.empty:
        priority_counts.columns = ["priority", "count"]
        fig = px.bar(priority_counts, x="priority", y="count", title="Companies By Priority")
        st.plotly_chart(fig, width="stretch")

    st.subheader("Top 20 Opportunities")
    if jobs.empty:
        st.info("No jobs available.")
    else:
        top_jobs = jobs.sort_values("fit_score", ascending=False, na_position="last").head(20)
        display = top_jobs[["company_name", "title", "location", "fit_score", "date_found", "url", "job_id"]]
        st.dataframe(display, width="stretch", hide_index=True)
        job_options = display["job_id"].astype(str).tolist()
        job_labels = [
            f"{row['company_name']} | {row['title']}"
            for _, row in display.iterrows()
        ]
        pick_col1, pick_col2 = st.columns([3, 1])
        with pick_col1:
            picked = st.selectbox(
                "Open a top opportunity",
                options=range(len(job_options)),
                format_func=lambda index: job_labels[index],
                key="analytics_top_job_pick",
            )
        with pick_col2:
            st.markdown("<div style='height: 1.6rem'></div>", unsafe_allow_html=True)
            if st.button("View Job", width="stretch"):
                select_job(job_options[picked])
                st.rerun()

    st.subheader("Most Recent Jobs")
    if jobs.empty:
        st.info("No recent jobs.")
    else:
        recent = jobs.sort_values("date_found", ascending=False, na_position="last").head(30)
        st.dataframe(
            recent[["company_name", "title", "date_found", "location", "job_id"]],
            width="stretch",
            hide_index=True,
        )

    st.subheader("Top Industries & Locations")
    info_col1, info_col2 = st.columns(2)
    with info_col1:
        st.markdown("**Top industry categories**")
        for industry, count in summary.get("top_industries", [])[:10]:
            st.markdown(f"- {industry}: {count}")
    with info_col2:
        st.markdown("**Top locations**")
        for location, count in summary.get("top_locations", [])[:10]:
            st.markdown(f"- {location}: {count}")


def _render_applied_jobs_flow() -> None:
    """Render a Sankey snapshot of every job that has reached Applied."""
    st.subheader("Applied jobs flow")
    st.caption(
        "Where applications stand now. Jobs remain in this view after moving beyond Applied."
    )
    try:
        tracked = list_tracked_jobs()
        history = list_application_stage_history()
    except Exception as exc:
        st.error(f"Failed to load tracked applications: {exc}")
        return

    labels, sources, targets, counts, applied_jobs = _build_application_flow(tracked, history)
    if not applied_jobs:
        st.info("No applied jobs yet. Mark a tracked job as Applied to start the flow.")
        return

    total = len(applied_jobs)
    stage_counts = pd.Series([row["stage"] for row in applied_jobs]).value_counts()
    interviewed_job_ids = {
        int(event["job_id"]) for event in history if event.get("stage") == "interviewing"
    }
    interviewed_companies = {
        row["company_id"] for row in applied_jobs if int(row["job_id"]) in interviewed_job_ids
    }
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Applications", total)
    m2.metric("Companies interviewed with", len(interviewed_companies))
    m3.metric("Offers", int(stage_counts.get("accepted", 0)))
    m4.metric(
        "Closed",
        int(stage_counts.get("rejected", 0) + stage_counts.get("withdrawn", 0)),
    )

    color_by_label = {
        "Applications submitted": TEAL_PRIMARY,
        "No response": STAGE_COLORS.get("applied", TEAL_PRIMARY),
        **{STAGE_LABELS[stage]: STAGE_COLORS.get(stage, "#64748b") for stage in STAGE_LABELS},
    }
    node_colors = [color_by_label.get(label, "#64748b") for label in labels]
    link_colors = [_hex_to_rgba(node_colors[target], 0.38) for target in targets]
    figure = go.Figure(
        go.Sankey(
            arrangement="snap",
            node={
                "label": labels,
                "color": node_colors,
                "pad": 24,
                "thickness": 24,
                "line": {"color": "rgba(15, 23, 42, 0.18)", "width": 1},
            },
            link={
                "source": sources,
                "target": targets,
                "value": counts,
                "color": link_colors,
            },
        )
    )
    figure.update_layout(
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        height=max(390, 70 * len(counts)),
        font={"size": 14},
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    st.caption(
        "The flow preserves every recorded stage transition; the table shows each application's current status."
    )

    detail = pd.DataFrame(applied_jobs)
    detail["Status"] = detail["stage"].map(STAGE_LABELS).fillna(detail["stage"])
    detail["Date applied"] = detail["applied_at"].fillna("").astype(str).str[:10]
    detail = detail.rename(
        columns={"company_name": "Company", "title": "Job position", "url": "Posting"}
    )
    st.dataframe(
        detail[["Job position", "Company", "Status", "Date applied", "Posting"]],
        width="stretch",
        hide_index=True,
        column_config={"Posting": st.column_config.LinkColumn(display_text="Open ↗")},
    )


def _build_application_flow(
    tracked: list[dict],
    history: list[dict],
) -> tuple[list[str], list[int], list[int], list[int], list[dict]]:
    """Build a Sankey from complete application journeys."""
    applied_jobs = [row for row in tracked if str(row.get("applied_at") or "").strip()]
    if not applied_jobs:
        return ["Applications submitted"], [], [], [], []

    stage_order = ("applied", "interviewing", "accepted", "rejected", "withdrawn")
    stage_labels = {**STAGE_LABELS, "applied": "No response"}
    events_by_job: dict[int, list[str]] = {}
    applied_ids = {int(row["job_id"]) for row in applied_jobs}
    for event in history:
        job_id = int(event["job_id"])
        stage = str(event["stage"])
        if job_id in applied_ids and stage in stage_order:
            journey = events_by_job.setdefault(job_id, [])
            if not journey or journey[-1] != stage:
                journey.append(stage)

    edge_counts: dict[tuple[str, str], int] = {}
    for job_id in applied_ids:
        journey = events_by_job.get(job_id, ["applied"])
        if not journey or journey[0] != "applied":
            journey.insert(0, "applied")
        path = ["submitted", *journey]
        for edge in zip(path, path[1:]):
            edge_counts[edge] = edge_counts.get(edge, 0) + 1

    present_stages = [stage for stage in stage_order if any(stage in edge for edge in edge_counts)]
    keys = ["submitted", *present_stages]
    labels = ["Applications submitted", *[stage_labels[stage] for stage in present_stages]]
    index = {key: position for position, key in enumerate(keys)}
    ordered_edges = sorted(edge_counts, key=lambda edge: (index[edge[0]], index[edge[1]]))
    sources = [index[source] for source, _ in ordered_edges]
    targets = [index[target] for _, target in ordered_edges]
    counts = [edge_counts[edge] for edge in ordered_edges]
    return labels, sources, targets, counts, applied_jobs


def _hex_to_rgba(color: str, alpha: float) -> str:
    """Convert a six-digit hex color to a Plotly-compatible rgba value."""
    value = color.lstrip("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _render_bar_chart(
    frame: pd.DataFrame,
    column: str,
    title: str,
    jobs: pd.DataFrame,
) -> None:
    if column == "industry" and not jobs.empty:
        counts = jobs.merge(
            frame[["company_name", column]].drop_duplicates(),
            on="company_name",
            how="left",
        )
        series = counts[column].fillna("Unknown")
    elif column in frame.columns:
        series = frame[column].fillna("Unknown")
    else:
        st.info(f"No data for {title}.")
        return

    counts = series.value_counts().head(10).reset_index()
    counts.columns = [column, "count"]
    if counts.empty:
        st.info(f"No data for {title}.")
        return
    fig = px.bar(counts, x=column, y="count", title=title)
    st.plotly_chart(fig, width="stretch")


def _render_status_chart(frame: pd.DataFrame, column: str, title: str) -> None:
    if column not in frame.columns or frame.empty:
        st.info(f"No data for {title}.")
        return
    counts = frame[column].fillna("Unknown").value_counts().reset_index()
    counts.columns = [column, "count"]
    fig = px.bar(counts, x=column, y="count", title=title)
    st.plotly_chart(fig, width="stretch")
