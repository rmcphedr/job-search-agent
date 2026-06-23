"""Company detail view for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.discovery.link_utils import clean_url
from src.ui.data_loader import get_company_detail, get_company_jobs, get_company_run_history
from src.ui.job_detail_view import render_job_detail_view
from src.ui.session_utils import clear_company_detail, select_job
from src.ui.status_utils import (
    CAREER_STATUS_FOUND,
    CAREER_STATUS_NOT_CHECKED,
    CAREER_STATUS_NOT_FOUND,
    JOB_STATUS_ERROR,
)


def render_company_detail_view(company_name: str | None = None) -> None:
    """Render a detailed company research page."""
    name = company_name or st.session_state.get("selected_company")
    if not name:
        st.warning("No company selected.")
        return

    if st.session_state.get("show_job_detail") and st.session_state.get("selected_job_id"):
        render_job_detail_view()
        return

    detail = get_company_detail(name)
    if detail is None:
        st.error(f"Company not found: {name}")
        if st.button("← Back to Companies"):
            clear_company_detail()
            st.rerun()
        return

    if st.button("← Back to Companies"):
        clear_company_detail()
        st.rerun()

    st.header(detail["company_name"])
    health_label, health_note = _company_health(detail)
    st.markdown(f"**Company health:** {health_label} — {health_note}")

    st.subheader("Company Overview")
    overview_col1, overview_col2 = st.columns(2)
    with overview_col1:
        st.markdown(f"**Website:** {detail.get('website') or '—'}")
        st.markdown(f"**Industry:** {detail.get('industry') or '—'}")
        st.markdown(f"**Location:** {detail.get('location') or '—'}")
        st.markdown(f"**Priority:** {detail.get('priority') or '—'}")
        st.markdown(f"**Hiring status:** {detail.get('hiring_status') or '—'}")
    with overview_col2:
        st.markdown(f"**Career page status:** {detail.get('career_page_status') or '—'}")
        st.markdown(f"**Job search status:** {detail.get('job_search_status') or '—'}")
        st.markdown(f"**Jobs found:** {detail.get('jobs_found', 0)}")
        st.markdown(f"**Last checked:** {detail.get('last_checked') or '—'}")
        st.markdown(f"**Career page:** {detail.get('career_page') or '—'}")

    link_col1, link_col2 = st.columns(2)
    website = clean_url(str(detail.get("website") or ""))
    career_page = clean_url(str(detail.get("career_page") or ""))
    with link_col1:
        if website:
            st.link_button("Open Website", website, width="stretch")
        else:
            st.button("Open Website", disabled=True, width="stretch")
    with link_col2:
        if career_page and career_page.upper() != "NOT FOUND":
            st.link_button("Open Career Page", career_page, width="stretch")
        else:
            st.button("Open Career Page", disabled=True, width="stretch")

    metadata = detail.get("metadata") or {}
    if _has_metadata(metadata, detail):
        st.subheader("Company Metadata")
        meta_col1, meta_col2 = st.columns(2)
        with meta_col1:
            _render_if_present("Company summary", metadata.get("company_summary") or detail.get("company_summary"))
            _render_if_present("Description", metadata.get("description"))
            _render_if_present("Specialties", metadata.get("specialties"))
        with meta_col2:
            _render_if_present("Source category", detail.get("source_category"))
            _render_if_present("Source directory", detail.get("source_id"))
            _render_if_present("Confidence", detail.get("confidence"))
            _render_if_present("Source URL", detail.get("source_url"))
        _render_if_present("Notes", metadata.get("raw_notes") or detail.get("notes"), full_width=True)

    st.subheader("Jobs Found At Company")
    jobs = get_company_jobs(name)
    if jobs.empty:
        st.info("No jobs discovered for this company yet.")
    else:
        display_jobs = jobs[["title", "location", "fit_score", "date_found", "active", "job_id"]].copy()
        display_jobs["active"] = display_jobs["active"].map(
            lambda value: "Yes" if str(value).strip().lower() in {"1", "true"} else "No"
        )
        st.dataframe(display_jobs, width="stretch", hide_index=True)

        job_labels = [
            f"{row['title']} | fit={row.get('fit_score', '—')}"
            for _, row in jobs.iterrows()
        ]
        selected_index = st.selectbox(
            "Select a job to view details",
            options=range(len(job_labels)),
            format_func=lambda index: job_labels[index],
            key=f"company_job_select_{name}",
        )
        selected_job = jobs.iloc[selected_index]
        if st.button("Open Job Detail", width="stretch"):
            select_job(selected_job["job_id"])
            st.rerun()

    st.subheader("Recent Discovery Activity")
    history = get_company_run_history(name)
    if not history:
        st.info("No history available.")
    else:
        for entry in history:
            st.markdown(
                f"- **{entry['run_type']}** at {entry['time']} — "
                f"checked={entry.get('companies_checked', '—')}, "
                f"detail={entry.get('detail', '—')}"
            )

    st.subheader("Coming Soon")
    future_col1, future_col2, future_col3, future_col4 = st.columns(4)
    with future_col1:
        st.button("Resume Tailoring", disabled=True, help="Coming Soon", key=f"resume_{name}")
    with future_col2:
        st.button("Cover Letter Generation", disabled=True, help="Coming Soon", key=f"cover_{name}")
    with future_col3:
        st.button("Outreach Generation", disabled=True, help="Coming Soon", key=f"outreach_{name}")
    with future_col4:
        st.button("Application Tracking", disabled=True, help="Coming Soon", key=f"track_{name}")


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
        st.text(text[:8000])
    else:
        st.markdown(f"**{label}:** {text[:500]}")
