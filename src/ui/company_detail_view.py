"""Company detail panel for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.discovery.link_utils import clean_url
from src.ui.data_loader import get_company_detail, get_company_jobs, get_company_run_history
from src.ui.session_utils import clear_company_detail, select_job
from src.ui.status_utils import (
    CAREER_STATUS_FOUND,
    CAREER_STATUS_NOT_CHECKED,
    CAREER_STATUS_NOT_FOUND,
    JOB_STATUS_ERROR,
)


def render_company_detail_panel(company_name: str) -> None:
    """Render a compact company preview in the right-side panel."""
    detail = get_company_detail(company_name)
    if detail is None:
        st.warning(f"Company not found: {company_name}")
        return

    health_label, health_note = _company_health(detail)
    st.markdown(f"### {detail['company_name']}")
    st.caption(f"{health_label} — {health_note}")

    evaluation = detail.get("evaluation")
    if evaluation:
        st.markdown("**Fit evaluation**")
        effective = evaluation.get("effective_fit_score", evaluation.get("fit_score"))
        fit_col1, fit_col2, fit_col3 = st.columns(3)
        fit_col1.metric("Composite", _format_score(effective))
        fit_col2.metric("Industry", _format_score(evaluation.get("industry_alignment")))
        fit_col3.metric("Mission", _format_score(evaluation.get("mission_alignment")))
        fit_col4, fit_col5, fit_col6 = st.columns(3)
        fit_col4.metric("Career", _format_score(evaluation.get("career_alignment")))
        fit_col5.metric("Growth", _format_score(evaluation.get("growth_potential")))
        fit_col6.metric("Confidence", _format_score(evaluation.get("confidence")))
        _render_if_present("Reasoning", evaluation.get("reasoning"), full_width=True)
        _render_if_present("Best roles", evaluation.get("best_roles"))
        _render_if_present("Interesting factors", evaluation.get("interesting_factors"))
        _render_if_present("Red flags", evaluation.get("red_flags"))
        if evaluation.get("calibration_feedback"):
            _render_if_present("Your calibration", evaluation.get("calibration_feedback"), full_width=True)
    else:
        st.info("No fit evaluation yet.")

    st.markdown("**Company details**")
    st.markdown(f"**Location:** {detail.get('location') or '—'}")
    st.markdown(f"**Industry:** {detail.get('industry') or '—'}")
    st.markdown(f"**Priority:** {detail.get('priority') or '—'}")
    st.markdown(f"**Hiring status:** {detail.get('hiring_status') or '—'}")
    st.markdown(f"**Career page status:** {detail.get('career_page_status') or '—'}")
    st.markdown(f"**Job search status:** {detail.get('job_search_status') or '—'}")
    st.markdown(f"**Last checked:** {detail.get('last_checked') or '—'}")

    pipeline_col1, pipeline_col2 = st.columns(2)
    with pipeline_col1:
        st.metric("Raw jobs", int(detail.get("last_raw_jobs") or 0))
        st.metric("Pre-screened", int(detail.get("last_prescreened_jobs") or 0))
    with pipeline_col2:
        st.metric("Triaged", int(detail.get("last_triaged_jobs") or 0))
        st.metric("Enriched", int(detail.get("last_enriched_jobs") or 0))
    st.metric("Active jobs saved", int(detail.get("jobs_found") or 0))

    website = clean_url(str(detail.get("website") or ""))
    career_page = clean_url(str(detail.get("career_page") or ""))
    link_col1, link_col2 = st.columns(2)
    with link_col1:
        if website:
            st.link_button("Website", website, width="stretch")
        else:
            st.button("Website", disabled=True, width="stretch", key=f"panel_website_{company_name}")
    with link_col2:
        if career_page and career_page.upper() != "NOT FOUND":
            st.link_button("Career page", career_page, width="stretch")
        else:
            st.button("Career page", disabled=True, width="stretch", key=f"panel_career_{company_name}")

    metadata = detail.get("metadata") or {}
    if _has_metadata(metadata, detail):
        with st.expander("Metadata & notes", expanded=False):
            _render_if_present("Company summary", metadata.get("company_summary") or detail.get("company_summary"))
            _render_if_present("Description", metadata.get("description"))
            _render_if_present("Specialties", metadata.get("specialties"))
            _render_if_present("Source category", detail.get("source_category"))
            _render_if_present("Source directory", detail.get("source_id"))
            _render_if_present("Confidence", detail.get("confidence"))
            _render_if_present("Source URL", detail.get("source_url"))
            _render_if_present("Notes", metadata.get("raw_notes") or detail.get("notes"), full_width=True)

    jobs = get_company_jobs(company_name)
    with st.expander(f"Jobs ({len(jobs)})", expanded=False):
        if jobs.empty:
            st.caption("No jobs discovered yet.")
        else:
            display_jobs = jobs[["title", "location", "fit_score", "date_found", "active", "job_id"]].copy()
            display_jobs["active"] = display_jobs["active"].map(
                lambda value: "Yes" if str(value).strip().lower() in {"1", "true"} else "No"
            )
            st.dataframe(display_jobs, width="stretch", hide_index=True)
            job_labels = [f"{row['title']} | fit={row.get('fit_score', '—')}" for _, row in jobs.iterrows()]
            selected_index = st.selectbox(
                "Open job",
                options=range(len(job_labels)),
                format_func=lambda index: job_labels[index],
                key=f"panel_company_job_select_{company_name}",
            )
            selected_job = jobs.iloc[selected_index]
            if st.button("View job detail", width="stretch", key=f"panel_open_job_{company_name}"):
                select_job(selected_job["job_id"])
                st.rerun()

    history = get_company_run_history(company_name)
    if history:
        with st.expander("Recent discovery activity", expanded=False):
            for entry in history:
                st.markdown(
                    f"- **{entry['run_type']}** at {entry['time']} — {entry.get('detail', '—')}"
                )


def render_company_detail_view(company_name: str | None = None) -> None:
    """Render a full-page company detail view (legacy navigation)."""
    name = company_name or st.session_state.get("selected_company")
    if not name:
        st.warning("No company selected.")
        return

    if st.session_state.get("show_job_detail") and st.session_state.get("selected_job_id"):
        from src.ui.job_detail_view import render_job_detail_view

        render_job_detail_view()
        return

    if st.button("← Back to Companies"):
        clear_company_detail()
        st.rerun()

    render_company_detail_panel(name)


def _format_score(value: object) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value)


def _company_health(detail: dict[str, object]) -> tuple[str, str]:
    career_status = str(detail.get("career_page_status", ""))
    job_status = str(detail.get("job_search_status", ""))
    jobs_found = int(detail.get("jobs_found") or 0)

    if career_status == CAREER_STATUS_FOUND and jobs_found > 0:
        return "🟢 Healthy", "Career page found and jobs discovered."
    if career_status == CAREER_STATUS_FOUND:
        return "🟡 Partial", "Career page found but no matching jobs yet."
    if (
        career_status in {CAREER_STATUS_NOT_FOUND, CAREER_STATUS_NOT_CHECKED}
        or job_status == JOB_STATUS_ERROR
    ):
        return "🔴 Missing", "Career page missing, not checked, or search error recorded."
    return "🟡 Partial", "Company profile is incomplete."


def _has_metadata(metadata: dict[str, object], detail: dict[str, object]) -> bool:
    fields = (
        metadata.get("description"),
        metadata.get("specialties"),
        metadata.get("company_summary"),
        detail.get("source_category"),
        detail.get("source_id"),
        detail.get("confidence"),
        detail.get("source_url"),
        detail.get("notes"),
    )
    return any(str(field).strip() for field in fields if field is not None)


def _render_if_present(label: str, value: object, *, full_width: bool = False) -> None:
    if value is None or not str(value).strip():
        return
    text = str(value).strip()
    if full_width:
        st.markdown(f"**{label}**")
        st.text(text[:4000])
    else:
        st.markdown(f"**{label}:** {text[:500]}")
