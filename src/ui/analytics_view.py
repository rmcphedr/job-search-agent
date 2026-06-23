"""Analytics view for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.ui.data_loader import load_analytics_data
from src.ui.job_detail_view import render_job_detail_view
from src.ui.session_utils import select_job


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
