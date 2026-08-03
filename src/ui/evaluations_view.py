"""Company fit evaluations view for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.orchestration.run_loader import load_calibration_summary, load_latest_run_manifest, load_run_summaries
from src.ui.data_loader import load_company_evaluations_frame
from src.ui.session_utils import select_company


def render_evaluations_view() -> None:
    st.header("Company Fit")
    st.caption("Agent evaluations from `data/company_evaluations.csv` and latest Hermes discovery runs.")

    evaluations = load_company_evaluations_frame()
    latest_run = load_latest_run_manifest()

    if latest_run is not None:
        st.subheader("Latest discovery run")
        counts = latest_run.counts
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Run ID", latest_run.run_id)
        c2.metric("Merged candidates", counts.candidates_merged)
        c3.metric("Evaluations merged", counts.evaluations_merged)
        c4.metric("Duplicates skipped", counts.candidates_duplicate)
        c5.metric("Status", latest_run.status)

        if latest_run.request:
            with st.expander("Run request", expanded=False):
                st.json(latest_run.request)

        calibration = load_calibration_summary(latest_run.run_id)
        if calibration:
            with st.expander("Calibration status", expanded=False):
                st.json(calibration)

    if evaluations.empty:
        st.info("No company evaluations yet. Run Hermes discovery + evaluation to populate `data/company_evaluations.csv`.")
        _render_run_history()
        return

    summary_col1, summary_col2, summary_col3 = st.columns(3)
    summary_col1.metric("Evaluated companies", len(evaluations))
    summary_col2.metric(
        "Avg fit score",
        f"{evaluations['effective_fit_score'].mean():.1f}" if "effective_fit_score" in evaluations.columns else "—",
    )
    calibrated_count = 0
    if "calibrated_fit_score" in evaluations.columns:
        calibrated_count = int(evaluations["calibrated_fit_score"].notna().sum())
    summary_col3.metric("User-calibrated", calibrated_count)

    st.subheader("Ranked company evaluations")
    display_columns = [
        "company_name",
        "effective_fit_score",
        "fit_score",
        "industry_alignment",
        "mission_alignment",
        "career_alignment",
        "growth_potential",
        "confidence",
        "run_id",
        "calibrated_at",
    ]
    available = [column for column in display_columns if column in evaluations.columns]
    ranked = evaluations.sort_values("effective_fit_score", ascending=False, na_position="last")
    st.dataframe(ranked[available], width="stretch", hide_index=True)

    pick_col1, pick_col2 = st.columns([3, 1])
    company_names = ranked["company_name"].tolist()
    with pick_col1:
        if company_names:
            picked_name = st.selectbox("Inspect company evaluation", options=company_names, key="eval_company_pick")
        else:
            picked_name = None
    with pick_col2:
        st.markdown("<div style='height: 1.6rem'></div>", unsafe_allow_html=True)
        if picked_name and st.button("View Company", width="stretch"):
            select_company(picked_name)
            st.session_state.show_company_detail = True
            st.rerun()

    if picked_name:
        row = ranked[ranked["company_name"] == picked_name].iloc[0]
        st.markdown(f"### {picked_name}")
        st.markdown(f"**Reasoning:** {row.get('reasoning', '—')}")
        if row.get("best_roles"):
            st.markdown(f"**Best roles:** {row.get('best_roles')}")
        if row.get("interesting_factors"):
            st.markdown(f"**Interesting factors:** {row.get('interesting_factors')}")
        if row.get("red_flags"):
            st.markdown(f"**Red flags:** {row.get('red_flags')}")
        if row.get("calibration_feedback"):
            st.markdown(f"**Your calibration note:** {row.get('calibration_feedback')}")

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        if "effective_fit_score" in evaluations.columns:
            fig = px.histogram(
                evaluations,
                x="effective_fit_score",
                nbins=10,
                title="Fit score distribution",
            )
            st.plotly_chart(fig, width="stretch")
    with chart_col2:
        if "run_id" in evaluations.columns:
            run_counts = (
                evaluations["run_id"].fillna("unknown").replace("", "unknown").value_counts().reset_index()
            )
            run_counts.columns = ["run_id", "count"]
            if not run_counts.empty:
                fig = px.bar(run_counts, x="run_id", y="count", title="Evaluations by run")
                st.plotly_chart(fig, width="stretch")

    _render_run_history()


def _render_run_history() -> None:
    summaries = load_run_summaries(limit=10)
    if not summaries:
        return
    st.subheader("Recent discovery runs")
    frame = pd.DataFrame(summaries)
    if frame.empty:
        return
    display = frame[["run_id", "status", "started_at", "counts"]]
    st.dataframe(display, width="stretch", hide_index=True)
