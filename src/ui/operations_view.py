"""Streamlit observability and guarded backlog controls."""

import streamlit as st

from src.ui.operations_data import enroll_backlog, load_model_efficiency, load_queue_metrics, load_recent_evaluation_runs, preview_backlog


def render_operations_view() -> None:
    st.title("Evaluation Operations")
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
