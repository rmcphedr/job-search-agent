"""Spreadsheet, detail, and preparation views for tracked applications."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.database.application_runs import (get_application_run, get_review_packet, approve_answer,
    set_application_mode, cancel_application, resume_application, transition_application)
from src.database.application_preparation import (
    start_application_preparation,
    update_application_step,
)
from src.database.application_submissions import (
    get_latest_application_submission,
    record_application_submission,
)
from src.database.application_workspace import (
    update_application_field,
)
from src.database.tracked_jobs import (
    STAGE_LABELS,
    TERMINAL_STAGES,
    TRACKING_STAGES,
    get_tracked_job,
    list_tracked_jobs,
    untrack_job,
    update_tracked_notes,
    update_tracked_stage,
)
from src.documents.resume_editor import (
    docx_to_html,
    editable_resume_path,
    render_docx_preview,
    save_html_to_docx,
)

from src.jobs.description_enrichment import mark_job_expired
from src.ui.actions import refresh_data
from src.ui.data_loader import get_current_job_by_id
from src.ui.review_view import render_job_summary_card, render_application_choices
from src.ui.theme import inject_tracking_theme

PIPELINE = ("tracked", "applying", "applied", "interviewing", "accepted")
TRACKING_TABLE_KEY = "tracked_jobs_table"


def render_tracking_view() -> None:
    inject_tracking_theme()
    mode = st.session_state.setdefault("tracking_view_mode", "table")
    job_id = st.session_state.get("tracking_selected_job_id")

    if mode == "preparation" and job_id:
        _render_preparation_view(int(job_id))
    elif mode == "detail" and job_id:
        _render_detail_view(int(job_id))
    else:
        _render_table_view()


def _render_table_view() -> None:
    st.markdown(
        '<div class="tracking-header"><h2>Tracked jobs</h2>'
        '<p>Your application pipeline in one place. Select a row to open its workspace.</p></div>',
        unsafe_allow_html=True,
    )
    tracked = list_tracked_jobs()
    if not tracked:
        st.info("No tracked jobs yet. Choose **Apply — track job** from the Review inbox.")
        return

    _render_stage_strip(tracked)
    show_archived = st.toggle("Show closed jobs", value=False)
    visible = tracked if show_archived else [row for row in tracked if row.get("stage") not in TERMINAL_STAGES]
    if not visible:
        st.info("All tracked jobs are closed. Turn on **Show closed jobs** to view them.")
        return
    frame = _tracking_frame(visible)
    event = st.dataframe(
        frame,
        key=TRACKING_TABLE_KEY,
        width="stretch",
        height=520,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "job_id": None,
            "Job position": st.column_config.TextColumn(width="large"),
            "Company": st.column_config.TextColumn(width="medium"),
            "Location": st.column_config.TextColumn(width="medium"),
            "Status": st.column_config.TextColumn(width="small"),
            "Fit": st.column_config.NumberColumn(format="%.1f", width="small"),
            "Date saved": st.column_config.TextColumn(width="small"),
            "Date applied": st.column_config.TextColumn(width="small"),
            "Posting": st.column_config.LinkColumn(width="small", display_text="Open ↗"),
        },
    )
    rows = list(getattr(getattr(event, "selection", None), "rows", []) or [])
    if rows:
        selected_id = int(frame.iloc[rows[0]]["job_id"])
        st.session_state.tracking_selected_job_id = str(selected_id)
        st.session_state.tracking_view_mode = "detail"
        st.rerun()


def _render_detail_view(job_id: int) -> None:
    job = get_current_job_by_id(job_id)
    tracked = get_tracked_job(job_id)
    if job is None or tracked is None:
        _render_unavailable_job()
        return

    if st.button("← All tracked jobs"):
        _back_to_table()
        st.rerun()

    header_col, action_col = st.columns([3, 1])
    with header_col:
        st.title(str(job.get("title") or "Job details"))
        st.markdown(f"### {job.get('company_name') or 'Unknown company'}")
        st.caption(f"Saved {str(tracked.get('created_at') or '')[:10]} · {job.get('location') or 'Location not listed'}")
    with action_col:
        fit = job.get("fit_score")
        if fit is not None and pd.notna(fit):
            st.metric("Degree of fit", f"{float(fit):.1f} / 10")

    _render_pipeline(str(tracked.get("stage", "tracked")))

    if str(tracked.get("stage")) in {"tracked", "applying"} or get_application_run(job_id):
        _render_application_run(job_id)

    submission = get_latest_application_submission(job_id)
    if submission:
        _render_submitted_application(submission, applied_at=str(tracked.get("applied_at") or ""))
    elif str(tracked.get("stage")) == "applying":
        st.info("Finished in the employer browser? Reconcile the reviewed dashboard data into a submitted snapshot.")
        if st.button("Mark application submitted", type="primary", width="stretch"):
            try:
                record_application_submission(job_id)
                refresh_data()
                st.success("Application moved to Applied and its submitted information was snapshotted.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if str(tracked.get("stage")) in {"tracked", "applying"}:
        label = "Continue preparing" if str(tracked.get("stage")) == "applying" else "Prepare application"
        if st.button(label, type="primary", width="stretch"):
            start_application_preparation(job_id)
            refresh_data()
            st.session_state.tracking_view_mode = "preparation"
            st.rerun()

    info_tab, description_tab, notes_tab = st.tabs(["Job information", "Full description", "Notes"])
    with info_tab:
        render_job_summary_card(job, show_posting_controls=False)
    with description_tab:
        url = str(job.get("url") or "").strip()
        if url:
            st.link_button("Open original application ↗", url)
        st.write(str(job.get("description") or "No job description was captured."))
    with notes_tab:
        notes = st.text_area("Private notes", value=str(tracked.get("notes") or ""), height=180)
        if st.button("Save notes"):
            update_tracked_notes(job_id, notes)
            refresh_data()
            st.success("Notes saved.")

    st.divider()
    control_col1, control_col2, control_col3 = st.columns(3)
    with control_col1:
        stage_options = [stage for stage, _ in TRACKING_STAGES]
        current = str(tracked.get("stage", "tracked"))
        new_stage = st.selectbox(
            "Pipeline status",
            stage_options,
            index=stage_options.index(current) if current in stage_options else 0,
            format_func=lambda value: STAGE_LABELS.get(value, value.title()),
        )
        if new_stage != current:
            update_tracked_stage(job_id, new_stage)
            refresh_data()
            st.rerun()
    with control_col2:
        if st.button("Mark posting expired", width="stretch"):
            mark_job_expired(job_id)
            refresh_data()
            _back_to_table()
            st.rerun()
    with control_col3:
        if st.button("Remove from tracking", width="stretch"):
            untrack_job(job_id)
            refresh_data()
            _back_to_table()
            st.rerun()


def _render_submitted_application(submission: dict, *, applied_at: str = "") -> None:
    snapshot = submission.get("snapshot") or {}
    st.subheader("Submitted application")
    applied_date = (applied_at or str(submission.get("submitted_at") or ""))[:10]
    st.metric("Date applied", applied_date or "Not recorded")
    st.caption(
        f"Confirmed {str(submission.get('submitted_at') or '')[:19].replace('T', ' ')} UTC"
        f" · {submission.get('provider') or 'Employer site'} · frozen local snapshot"
    )
    with st.expander("Contact details"):
        _render_snapshot_values(snapshot.get("contact_details") or [])
    documents = snapshot.get("documents") or []
    with st.expander("Resume"):
        _render_submitted_document(documents, "resume", "Resume")
    with st.expander("Cover letter"):
        _render_submitted_document(documents, "cover_letter", "Cover letter")
    with st.expander("Questions"):
        questions = snapshot.get("questions") or []
        if questions:
            _render_snapshot_values(questions)
        else:
            _render_snapshot_values(snapshot.get("application_fields") or [])


def _render_snapshot_values(rows: list[dict]) -> None:
    if not rows:
        st.caption("No submitted values were recorded for this section.")
        return
    for row in rows:
        label = str(row.get("label") or row.get("field_key") or row.get("fact_key") or "Field")
        value = str(row.get("value") or "").strip()
        disposition = str(row.get("disposition") or "")
        st.markdown(f"**{label}**")
        st.write(value or ("Skipped" if disposition == "skipped" else "Not recorded"))


def _render_submitted_document(documents: list[dict], field_key: str, label: str) -> None:
    row = next((item for item in documents if item.get("field_key") == field_key), None)
    value = str((row or {}).get("value") or "")
    path = editable_resume_path(value)
    if path is None:
        st.caption(f"No submitted {label.lower()} file was recorded.")
        return
    st.caption(str(path))
    st.download_button(
        f"Download {label.lower()}",
        data=Path(path).read_bytes(),
        file_name=Path(path).name,
        key=f"download_submission_{field_key}_{submission_file_key(path)}",
    )
    preview_path, preview_error = render_docx_preview(path)
    if preview_path and preview_path.suffix.lower() == ".pdf":
        st.pdf(str(preview_path), height=720)
    elif preview_path:
        st.image(str(preview_path), width="stretch")
    elif preview_error:
        st.info(preview_error)


def submission_file_key(path: Path) -> str:
    return str(path).replace("/", "_").replace(" ", "_")


def _render_preparation_view(job_id: int) -> None:
    job = get_current_job_by_id(job_id)
    tracked = get_tracked_job(job_id)
    if job is None or tracked is None:
        _render_unavailable_job()
        return

    if st.button("← Job details"):
        st.session_state.tracking_view_mode = "detail"
        st.rerun()

    st.title("Prepare application")
    st.markdown(f"### {job.get('title')} · {job.get('company_name')}")
    _render_pipeline("applying")

    _render_application_workspace(job_id, str(job.get("url") or ""))


def _render_application_workspace(job_id: int, source_url: str) -> None:
    _render_application_run(job_id)


def _run_control(action, *args) -> None:
    try:
        action(*args)
    except ValueError as exc:
        st.error(str(exc))
    else:
        refresh_data()
        st.rerun()


def _authorize_completion(run_id: int) -> None:
    set_application_mode(run_id, "fully_automate")
    transition_application(run_id, "queued")


def _render_application_run(job_id: int) -> None:
    run = get_application_run(job_id)
    if not run:
        render_application_choices(job_id)
        return
    packet = get_review_packet(run["run_id"])
    run_id, status = run["run_id"], run["status"]
    st.subheader("Application worker")
    if st.button("Refresh progress", key=f"refresh_run_{run_id}"):
        refresh_data()
        st.rerun()
    st.write(f"Mode: {run['mode'].replace('_', ' ')} · Status: {status.replace('_', ' ')}")
    if run.get("pause_reason"):
        st.warning(f"Handoff: {run['pause_reason']}")
    session = packet.get("session") or {}
    if session.get("application_url"):
        st.link_button("Employer application", session["application_url"])
    st.caption(f"Current page: {session.get('current_page') or 'Waiting for inspection'}")
    if status == "submission_uncertain":
        st.error("Submission uncertain — inspect the employer portal or reconcile a confirmed manual submission below. Do not retry submission.")
    if status == "ready_for_review":
        st.info("Draft packet ready. The worker stopped before final submission. Review the packet or take over the employer browser.")
    editable = status in {"needs_user", "ready_for_review"} and not run.get("submission_attempted_at")
    st.markdown("#### Review packet")
    st.write({key: packet.get(key) for key in ("artifacts", "pages", "remaining", "validation")})
    for field in packet.get("fields", []):
        key = field["field_key"]
        draft = packet.get("drafts", {}).get(key)
        st.write(f"{field.get('label', key)} · {field.get('status', 'pending')}")
        if draft:
            st.caption(f"Draft: {draft.get('approval_status', 'unavailable')} · Sources: {', '.join(draft.get('evidence_refs', []))}")
            value = st.text_area(field.get("label", key), value=field.get("value") or draft.get("answer", ""), key=f"run_answer_{run_id}_{key}", disabled=not editable)
            if editable and st.button("Approve answer", key=f"approve_{run_id}_{key}"):
                _run_control(approve_answer, run_id, key, value)
        else:
            st.write(field.get("value") or "Not provided")
    if editable:
        for section in ("resume", "cover_letter"):
            fields = [f for f in packet.get("fields", []) if f.get("section") == section]
            if fields:
                _render_workspace_section(job_id, section, fields)
    mutable = status not in {"submitted", "cancelled", "failed", "submission_uncertain", "submitting"} and not run.get("submission_attempted_at")
    if mutable:
        modes = ["fully_automate", "draft_for_review"]
        mode = st.selectbox("Run mode", modes, index=modes.index(run["mode"]), format_func=lambda x: x.replace("_", " ").title(), key=f"mode_{run_id}")
        if st.button("Save mode", key=f"save_mode_{run_id}"):
            _run_control(set_application_mode, run_id, mode)
        if status == "needs_user" and st.button("Resume", key=f"resume_{run_id}"):
            _run_control(resume_application, run_id)
        if status == "ready_for_review" and st.button("Authorize agent to finish and submit", key=f"finish_{run_id}"):
            _run_control(_authorize_completion, run_id)
        if st.button("Cancel application", key=f"cancel_{run_id}"):
            _run_control(cancel_application, run_id)
        st.caption("Cancellation stops local work; it does not undo data already saved by the employer.")
    st.caption("Run the local worker separately: python -m src.orchestration.application_worker --watch")


def _render_workspace_section(job_id: int, section: str, fields: list[dict]) -> None:
    if section == "resume":
        current = next((str(field.get("value") or "") for field in fields if field.get("field_key") == "resume"), "")
        _render_resume_controls(job_id, current)

    edited_values: dict[str, str] = {}
    for field in fields:
        required = " *" if field.get("required") else ""
        field_key = str(field["field_key"])
        widget_key = f"application_field_{job_id}_{field_key}"
        pending_key = f"pending_application_field_{job_id}_{field_key}"
        if pending_key in st.session_state:
            st.session_state[widget_key] = st.session_state.pop(pending_key)
        options = json.loads(str(field.get("options_json") or "[]"))
        current = str(field.get("value") or "")
        if options:
            choices = [""] + [str(option) for option in options]
            value = st.selectbox(
                f"{field['label']}{required}", choices,
                index=choices.index(current) if current in choices else 0,
                key=widget_key,
            )
        else:
            value = st.text_input(
                f"{field['label']}{required}", value=current, key=widget_key,
                type="password" if field.get("field_type") == "password" else "default",
                help="Local document path used by the employer application." if field.get("field_type") == "file" else None,
            )
        edited_values[field_key] = value
        if field_key == "cover_letter":
            _render_cover_letter_controls(job_id, value)
    if fields and st.button(f"Save {section.replace('_', ' ')}", type="primary", key=f"save_section_{job_id}_{section}"):
        for field_key, value in edited_values.items():
            update_application_field(job_id, field_key, value)
        refresh_data()
        st.success("Saved.")
        st.rerun()
    if section == "cover_letter":
        st.caption("Optional when offered by the provider, but included by default for review.")


def _render_resume_controls(job_id: int, value: str) -> None:
    _render_docx_editor(job_id, "resume", value, "Resume")


def _render_cover_letter_controls(job_id: int, value: str) -> None:
    _render_docx_editor(job_id, "cover_letter", value, "Cover letter")


def _render_docx_editor(job_id: int, field_key: str, value: str, label: str) -> None:
    """Show an inline editor for a generated DOCX without changing its path."""
    path = editable_resume_path(value)
    if path is None:
        if value:
            st.caption("Inline editing is available when this points to an existing DOCX file.")
        return

    state_key = f"document_editor_content_{job_id}_{field_key}_{path}"
    if state_key not in st.session_state:
        try:
            st.session_state[state_key] = docx_to_html(path)
        except Exception as exc:
            st.error(f"The resume could not be opened: {exc}")
            return

    st.caption(f"Editing {path.name}. Save rebuilds this file; preview shows the rendered document.")
    editor_column, preview_column = st.columns([1, 1], gap="large")
    with editor_column:
        st.markdown("#### Edit content")
        try:
            from streamlit_quill import st_quill

            edited = st_quill(
                value=st.session_state[state_key],
                html=True,
                toolbar=[
                    ["bold", "italic", "underline"],
                    [{"header": [1, 2, 3, False]}],
                    [{"list": "ordered"}, {"list": "bullet"}],
                    [{"align": []}],
                    ["clean"],
                ],
                key=f"document_quill_{job_id}_{field_key}_{path}",
            )
        except ImportError:
            st.warning("Rich formatting needs `streamlit-quill`; editing is available as HTML for now.")
            edited = st.text_area(
                f"{label} content",
                value=st.session_state[state_key],
                height=620,
                key=f"document_html_{job_id}_{field_key}_{path}",
            )

        if st.button(f"Save and rebuild {label.lower()}", type="primary", key=f"save_document_{job_id}_{field_key}_{path}"):
            try:
                save_html_to_docx(path, edited or "")
                st.session_state[state_key] = edited or ""
                update_application_field(job_id, field_key, str(path))
                st.success(f"{label} saved to {path}")
                st.rerun()
            except Exception as exc:
                st.error(f"The {label.lower()} could not be saved: {exc}")

    with preview_column:
        st.markdown("#### Final document preview")
        preview_path, preview_error = render_docx_preview(path)
        if preview_path and preview_path.suffix.lower() == ".pdf":
            st.pdf(str(preview_path), height=720)
        elif preview_path:
            st.image(str(preview_path), width="stretch")
            st.caption("macOS Quick Look preview. Install LibreOffice for multi-page PDF rendering.")
        else:
            st.info(preview_error or "A preview could not be generated.")


def _render_preparation_step(job_id: int, step: dict) -> None:
    status = str(step.get("status", "pending"))
    icon = "✓" if status in {"complete", "not_required"} else "◌" if status == "pending" else "↻"
    label = f"{icon}  {step.get('position')}. {step.get('title')}"
    with st.expander(label, expanded=status == "in_progress"):
        status_options = ["pending", "in_progress", "complete", "not_required"]
        new_status = st.selectbox(
            "Status",
            status_options,
            index=status_options.index(status),
            format_func=lambda value: value.replace("_", " ").title(),
            key=f"prep_status_{job_id}_{step['step_key']}",
        )
        details = st.text_area(
            "Agent output / reviewed information",
            value=str(step.get("details") or ""),
            placeholder="The application agent's findings and changes will appear here.",
            height=120,
            key=f"prep_details_{job_id}_{step['step_key']}",
        )
        if st.button("Save step", key=f"prep_save_{job_id}_{step['step_key']}"):
            update_application_step(
                job_id,
                str(step["step_key"]),
                status=new_status,
                details=details,
            )
            refresh_data()
            st.rerun()


def _render_stage_strip(tracked: list[dict]) -> None:
    counts = {stage: sum(str(row.get("stage")) == stage for row in tracked) for stage in PIPELINE}
    columns = st.columns(len(PIPELINE))
    for column, stage in zip(columns, PIPELINE, strict=True):
        with column:
            st.metric(STAGE_LABELS.get(stage, stage.title()), counts[stage])


def _render_pipeline(current: str) -> None:
    try:
        current_index = PIPELINE.index(current)
    except ValueError:
        current_index = 0
    items = []
    for index, stage in enumerate(PIPELINE):
        state = "current" if index == current_index else "done" if index < current_index else "future"
        items.append(
            f'<div class="pipeline-step {state}">{html.escape(STAGE_LABELS.get(stage, stage.title()))}</div>'
        )
    st.markdown(f'<div class="pipeline-strip">{"".join(items)}</div>', unsafe_allow_html=True)


def _tracking_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "job_id": frame["job_id"].astype(int),
            "Job position": frame["title"],
            "Company": frame["company_name"],
            "Location": frame["location"].fillna("—"),
            "Status": frame["stage"].map(lambda value: STAGE_LABELS.get(str(value), str(value).title())),
            "Fit": pd.to_numeric(frame["fit_score"], errors="coerce"),
            "Date saved": frame["created_at"].fillna("").astype(str).str[:10],
            "Date applied": frame["applied_at"].fillna("—").astype(str).str[:10],
            "Posting": frame["url"].fillna(""),
        }
    )


def _back_to_table() -> None:
    st.session_state.tracking_view_mode = "table"
    st.session_state.tracking_selected_job_id = None


def _render_unavailable_job() -> None:
    st.error("This tracked job is no longer available.")
    if st.button("← All tracked jobs"):
        _back_to_table()
        st.rerun()
