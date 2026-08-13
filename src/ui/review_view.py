"""Fast, one-job-at-a-time review inbox."""

from __future__ import annotations

import html
import json

import pandas as pd
import streamlit as st

from src.database.job_reviews import get_review_decisions, set_review_decision
from src.database.tracked_jobs import get_tracked_stage_map, track_job
from src.jobs.description_enrichment import mark_job_expired
from src.ui.actions import refresh_data
from src.ui.data_loader import load_jobs_from_db, parse_fit_reason


def render_review_view() -> None:
    """Render the highest-fit untracked job and quick-review actions."""
    _inject_review_theme()
    st.markdown(
        """
        <div class="review-heading">
          <div><span class="review-eyebrow">JOB INBOX</span><h1>Quick review</h1></div>
          <div class="review-heading-copy">Decide what deserves your attention. One role at a time.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    jobs = load_jobs_from_db()
    if jobs.empty:
        st.info("No jobs are ready for review yet. Run job discovery to fill the inbox.")
        return

    min_fit = st.slider("Minimum fit", 0.0, 10.0, 7.0, 0.5, help="Only show evaluated jobs at or above this score.")
    inbox = _build_inbox(jobs, min_fit)
    if inbox.empty:
        pending = int(jobs["evaluated_at"].isna().sum()) if "evaluated_at" in jobs.columns else 0
        if pending:
            st.info(
                f"{pending} active jobs are waiting for a full profile evaluation. "
                "Quick Review only shows jobs with current, structured match details."
            )
        else:
            st.success("Inbox cleared — there are no matching jobs waiting for review.")
        return

    current_index = min(int(st.session_state.get("review_index", 0)), len(inbox) - 1)
    st.session_state.review_index = current_index
    job = inbox.iloc[current_index].to_dict()

    top_left, top_right = st.columns([3, 1])
    with top_left:
        st.caption(f"{current_index + 1} of {len(inbox)} jobs in this inbox")
    with top_right:
        fit = float(job["fit_score"])
        st.markdown(f'<div class="fit-pill">{fit:.1f} / 10 fit</div>', unsafe_allow_html=True)

    render_job_summary_card(job)
    _render_actions(int(job["job_id"]), len(inbox))


def _build_inbox(jobs: pd.DataFrame, min_fit: float) -> pd.DataFrame:
    decisions = get_review_decisions()
    tracked = get_tracked_stage_map()
    frame = jobs.copy()
    frame = frame[frame["active"].astype(str).str.lower().isin({"1", "true"})]
    frame["fit_score"] = pd.to_numeric(frame["fit_score"], errors="coerce")
    frame = frame[frame["fit_score"].notna() & (frame["fit_score"] >= min_fit)]
    if "fit_details" in frame.columns:
        frame = frame[frame["fit_details"].map(_has_structured_assessment)]
    frame = frame[~frame["job_id"].astype(int).isin(tracked)]
    frame["review_decision"] = frame["job_id"].astype(int).map(decisions)
    frame = frame[frame["review_decision"].isna() | (frame["review_decision"] == "maybe")]
    frame["maybe_rank"] = (frame["review_decision"] == "maybe").astype(int)
    return frame.sort_values(["maybe_rank", "fit_score", "date_found"], ascending=[True, False, False]).reset_index(drop=True)


def render_job_summary_card(job: dict, *, show_posting_controls: bool = True) -> None:
    """Render the shared glanceable job and fit summary card."""
    _inject_review_theme()
    title = html.escape(_clean_text(job.get("title")) or "Untitled role")
    company = html.escape(_clean_text(job.get("company_name")) or "Unknown company")
    details = _fit_details(job.get("fit_details"))
    reason = str(details.get("why_fit") or _fit_summary(job.get("fit_reason")))
    summary = _role_summary(details.get("role_summary"), job.get("description"))
    assessments = _qualification_assessments(details, job.get("matched_keywords"))
    score = float(job.get("fit_score") or 0)
    fit_label = "Strong fit" if score >= 8 else "Good fit" if score >= 7 else "Possible fit"

    summary_html = "".join(f"<li>{html.escape(item)}</li>" for item in summary[:4])
    qualifications_html = "".join(_qualification_html(item) for item in assessments[:8])
    chips = [
        _clean_text(job.get("location")),
        _clean_text(details.get("salary")),
        _clean_text(details.get("seniority")),
        _clean_text(details.get("employment_type")),
    ]
    chips_html = "".join(f"<span>{html.escape(value)}</span>" for value in chips if value)

    st.markdown(
        f"""
        <div class="review-card">
          <section class="review-role">
            <div class="company-mark">{company[:1].upper()}</div>
            <div class="role-title">{title}</div>
            <div class="role-company">{company}</div>
            <div class="role-chips">{chips_html}</div>
            <div class="fit-inline">✓ {score:.1f}/10 · {fit_label}</div>
            <h3>Summary</h3>
            <ul class="summary-list">{summary_html}</ul>
          </section>
          <section class="review-fit">
            <h3>✣ Why this might fit</h3>
            <p class="fit-copy">{html.escape(reason)}</p>
            <h3>Qualifications</h3>
            <ul class="qualification-list">{qualifications_html}</ul>
          </section>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not show_posting_controls:
        return

    url = _clean_text(job.get("url"))
    link_col, expired_col = st.columns([2, 1])
    with link_col:
        if url:
            st.link_button("View original posting ↗", url, width="stretch")
    with expired_col:
        if st.button("Mark expired", key=f"review_expired_{int(job['job_id'])}", width="stretch"):
            mark_job_expired(int(job["job_id"]))
            refresh_data()
            st.rerun()


def _render_actions(job_id: int, inbox_size: int) -> None:
    no_col, maybe_col, apply_col = st.columns([1, 1, 1.25])
    with no_col:
        if st.button("No — remove", key=f"review_no_{job_id}", width="stretch"):
            set_review_decision(job_id, "declined")
            _after_decision()
    with maybe_col:
        if st.button("Maybe — later", key=f"review_maybe_{job_id}", width="stretch"):
            set_review_decision(job_id, "maybe")
            _after_decision()
    with apply_col:
        if st.button("Apply — track job", key=f"review_apply_{job_id}", type="primary", width="stretch"):
            track_job(job_id)
            set_review_decision(job_id, "accepted")
            _after_decision()

    st.caption("Maybe jobs stay in the inbox and rotate behind unreviewed roles." if inbox_size > 1 else "Your decision is saved immediately.")


def _after_decision() -> None:
    st.session_state.review_index = 0
    refresh_data()
    st.rerun()


def _fit_summary(value: object) -> str:
    parsed = parse_fit_reason(value)
    for key in ("why_fit", "reason", "summary"):
        if parsed.get(key):
            return str(parsed[key])
    text = str(value or "").strip()
    return text if text and not text.startswith("{") else "This role scored highly against your current profile and preferences."


def _matched_keywords(value: object) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        text = str(value or "").strip()
        try:
            decoded = json.loads(text)
            items = decoded if isinstance(decoded, list) else []
        except (json.JSONDecodeError, TypeError):
            items = [part.strip() for part in text.split(",") if part.strip()]
    return [str(item) for item in items[:5]]


def _fit_details(value: object) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or ""))
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _has_structured_assessment(value: object) -> bool:
    assessment = _fit_details(value).get("qualification_assessment")
    return isinstance(assessment, list) and bool(assessment)


def _detail_items(value: object) -> list[str]:
    return [_clean_text(item) for item in value if _clean_text(item)] if isinstance(value, list) else []


def _qualification_assessments(details: dict, matched_keywords: object) -> list[dict[str, object]]:
    """Return one match/gap decision per qualification, with legacy fallback."""
    structured = details.get("qualification_assessment")
    if isinstance(structured, list):
        rows = [item for item in structured if isinstance(item, dict) and _clean_text(item.get("requirement"))]
        if rows:
            return rows

    matches = _detail_items(details.get("skills_match")) or _matched_keywords(matched_keywords)
    gaps = _detail_items(details.get("skill_gaps"))
    return [
        {"requirement": item, "status": "match", "evidence": "", "preferred": False}
        for item in matches
    ] + [
        {"requirement": item, "status": "gap", "evidence": "", "preferred": False}
        for item in gaps
    ]


def _qualification_html(item: dict[str, object]) -> str:
    status = "match" if item.get("status") == "match" else "gap"
    icon = "✓" if status == "match" else "×"
    requirement = html.escape(_clean_text(item.get("requirement")))
    evidence = html.escape(_clean_text(item.get("evidence")))
    preferred = '<span class="preferred-tag">Preferred</span>' if item.get("preferred") else ""
    evidence_html = f'<small>{evidence}</small>' if evidence else ""
    return (
        f'<li class="{status}"><span class="qual-icon">{icon}</span>'
        f'<div><strong>{requirement}</strong>{preferred}{evidence_html}</div></li>'
    )


def _clean_text(value: object) -> str:
    """Return display text without leaking pandas/JSON missing-value sentinels."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "none", "null", "n/a", "na"} else text


def _role_summary(value: object, description: object) -> list[str]:
    structured = _detail_items(value)
    if structured:
        return structured
    text = " ".join(str(description or "").split())
    if not text:
        return ["No full description was captured. Open the original posting for details."]
    sentences = [item.strip() for item in text.replace("•", ". ").split(".") if len(item.strip()) >= 24]
    return sentences[:3] or [text[:180].rstrip() + ("…" if len(text) > 180 else "")]


def _inject_review_theme() -> None:
    st.markdown(
        """
        <style>
        .review-heading { display:flex; align-items:end; justify-content:space-between; margin:.4rem 0 1.2rem; }
        .review-heading h1 { margin:.15rem 0 0; letter-spacing:-.04em; }
        .review-eyebrow,.section-label { color:#6d28d9; font-size:.72rem; font-weight:800; letter-spacing:.12em; }
        .review-heading-copy { color:#64748b; max-width:24rem; text-align:right; padding-bottom:.4rem; }
        .fit-pill { background:#ecfdf5; border:1px solid #a7f3d0; color:#047857; border-radius:999px; padding:.35rem .75rem; font-weight:800; text-align:center; }
        .review-card { display:grid; grid-template-columns:1fr 1fr; background:#fff; border:1px solid #e2e8f0; border-radius:20px; box-shadow:0 14px 38px rgba(15,23,42,.07); overflow:hidden; margin:.35rem 0 1rem; }
        .review-role,.review-fit { padding:2rem; }
        .review-fit { background:#f8fafc; margin:1rem; border-radius:14px; padding:1.35rem 1.5rem; }
        .company-mark { width:2.7rem; height:2.7rem; display:grid; place-items:center; border-radius:12px; background:#7c3aed; color:white; font-weight:900; margin-bottom:1.1rem; }
        .role-title { font-size:1.55rem; line-height:1.15; font-weight:850; color:#1e1b4b; }
        .role-company { font-weight:700; color:#475569; margin-top:.35rem; }
        .role-chips { display:flex; flex-wrap:wrap; gap:.5rem; margin:1rem 0 .7rem; }
        .role-chips span { background:#f1f5f9; border-radius:999px; padding:.38rem .7rem; color:#475569; font-size:.82rem; }
        .fit-inline { display:inline-block; background:#ecfdf5; color:#047857; border-radius:999px; padding:.4rem .72rem; font-weight:750; font-size:.86rem; margin-bottom:1.1rem; }
        .review-card h3 { color:#0f172a; font-size:1rem; margin:1rem 0 .65rem; }
        .review-card p { color:#334155; line-height:1.55; margin-top:.25rem; }
        .fit-copy { font-size:.96rem; }
        .summary-list,.qualification-list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:.5rem; }
        .summary-list li { color:#334155; line-height:1.45; }
        .job-requirements { margin:.1rem 0 0; padding-left:1.1rem; color:#334155; display:flex; flex-direction:column; gap:.38rem; line-height:1.35; }
        .qualification-list li { display:flex; gap:.6rem; color:#334155; line-height:1.35; }
        .qualification-list .qual-icon { flex:0 0 auto; font-weight:900; }
        .qualification-list .match .qual-icon { color:#10b981; }
        .qualification-list .gap .qual-icon { color:#e11d48; }
        .qualification-list strong { display:inline; font-size:.88rem; }
        .qualification-list small { display:block; color:#64748b; margin-top:.12rem; font-size:.78rem; }
        .preferred-tag { display:inline-block; margin-left:.4rem; padding:.08rem .35rem; border-radius:999px; background:#ede9fe; color:#6d28d9; font-size:.65rem; font-weight:750; vertical-align:middle; }
        .qual-label { color:#64748b; font-size:.78rem; font-weight:750; margin:.35rem 0 .5rem; }
        .gaps-label { margin-top:1rem; }
        .muted-item { color:#94a3b8 !important; font-size:.86rem; }
        @media (max-width: 800px) { .review-card { grid-template-columns:1fr; } .review-fit { border-left:0; border-top:1px solid #ede9fe; } .review-heading-copy { display:none; } }
        </style>
        """,
        unsafe_allow_html=True,
    )
