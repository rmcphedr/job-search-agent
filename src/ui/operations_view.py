"""Streamlit observability and guarded backlog controls."""

import streamlit as st
import pandas as pd
from src.database.db import get_connection

from src.ui.operations_data import enroll_backlog, load_model_efficiency, load_queue_metrics, load_recent_evaluation_runs, preview_backlog


def render_operations_view() -> None:
    st.title("Operations")
    st.subheader("Application worker")
    db = get_connection()
    try:
        rows = [dict(row) for row in db.execute("SELECT r.*, COALESCE(s.provider, 'unknown') AS provider FROM application_runs r LEFT JOIN application_sessions s ON s.job_id=r.job_id")]
    finally:
        db.close()
    st.dataframe(application_metrics(rows), width="stretch")
    st.caption("Elapsed seconds: approval to latest checkpoint or completion, grouped by current status and provider.")
    st.subheader("Evaluation operations")
    st.caption("Queueing never starts a model run. Evaluation is initiated separately with explicit caps.")
    m = load_queue_metrics(); cols = st.columns(6)
    for col, label, value in zip(cols, ("Ready","Deferred","Claimed","Failed","Completed","Stale"), (m.ready,m.deferred,m.claimed,m.failed,m.completed,m.stale)):
        col.metric(label, value)
    st.subheader("Historical backlog")
    st.warning("Historical jobs are never enrolled automatically.")
    limit = st.number_input("Maximum jobs", 1, 100, 10)
    token_limit = st.number_input("Estimated token ceiling", 1000, 1000000, 50000, step=1000)
    rows = preview_backlog(limit=int(limit), verified_only=True)
    selected = st.dataframe([r.__dict__ for r in rows], on_select="rerun", selection_mode="multi-row", key="backlog_selection")
    confirm = st.checkbox("I confirm enrollment of the selected jobs. This does not start evaluation.")
    indices = selected.selection.rows if selected else []
    if st.button("Enroll selected jobs", disabled=not confirm or not indices):
        count = enroll_backlog([rows[i].job_id for i in indices], confirm=True, max_jobs=int(limit), token_limit=int(token_limit))
        st.success(f"Enrolled {count} jobs. No model run was started.")
    st.code("python3 -m src.orchestration.evaluation_cli claim --run-id <run-id> --worker-id codex")
    st.subheader("Recent runs"); st.dataframe(load_recent_evaluation_runs(), width="stretch")
    st.subheader("Model efficiency"); st.dataframe(load_model_efficiency(), width="stretch")


def application_metrics(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["status", "provider", "count", "elapsed_seconds"])
    frame = pd.DataFrame(rows)
    frame["elapsed_seconds"] = (pd.to_datetime(frame["updated_at"], utc=True, format="mixed") - pd.to_datetime(frame["created_at"], utc=True, format="mixed")).dt.total_seconds().clip(lower=0)
    return frame.groupby(["status", "provider"], dropna=False).agg(count=("status", "size"), elapsed_seconds=("elapsed_seconds", "mean")).reset_index()
