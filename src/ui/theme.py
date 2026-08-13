"""Teal dashboard theme helpers for job tracking UI."""

from __future__ import annotations

import streamlit as st

from src.database.tracked_jobs import STAGE_LABELS

TEAL_PRIMARY = "#0f766e"
TEAL_ACCENT = "#14b8a6"
TEAL_LIGHT = "#ccfbf1"
TEAL_MUTED = "#5eead4"
TEAL_DARK = "#115e59"

STAGE_COLORS: dict[str, str] = {
    "tracked": "#64748b",
    "applying": "#0ea5e9",
    "applied": TEAL_PRIMARY,
    "interviewing": "#7c3aed",
    "accepted": "#059669",
    "rejected": "#dc2626",
    "withdrawn": "#94a3b8",
}


def inject_tracking_theme() -> None:
    """Inject global CSS for teal tracking accents."""
    st.markdown(
        f"""
        <style>
        :root {{
            --tracking-teal: {TEAL_PRIMARY};
            --tracking-teal-light: {TEAL_LIGHT};
            --tracking-teal-accent: {TEAL_ACCENT};
        }}
        .tracking-header {{
            background: linear-gradient(135deg, {TEAL_LIGHT} 0%, #f0fdfa 100%);
            border: 1px solid {TEAL_MUTED};
            border-radius: 12px;
            padding: 1rem 1.25rem;
            margin-bottom: 1rem;
        }}
        .tracking-stage-badge {{
            display: inline-block;
            padding: 0.15rem 0.55rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            color: white;
            margin-right: 0.35rem;
        }}
        .tracking-card {{
            border: 1px solid {TEAL_MUTED};
            border-left: 4px solid {TEAL_PRIMARY};
            border-radius: 10px;
            padding: 0.75rem 0.9rem;
            margin-bottom: 0.55rem;
            background: #ffffff;
        }}
        .tracking-card-title {{
            font-weight: 600;
            color: {TEAL_DARK};
            margin-bottom: 0.15rem;
        }}
        .tracking-card-meta {{
            color: #475569;
            font-size: 0.82rem;
        }}
        .tracking-column-header {{
            color: {TEAL_DARK};
            font-weight: 700;
            border-bottom: 2px solid {TEAL_ACCENT};
            padding-bottom: 0.35rem;
            margin-bottom: 0.5rem;
        }}
        .tracking-header h2 {{ margin:0; color:{TEAL_DARK}; }}
        .tracking-header p {{ margin:.35rem 0 0; color:#334155; }}
        .pipeline-strip {{
            display:grid; grid-template-columns:repeat(5,1fr); margin:1rem 0 1.25rem;
            border:1px solid #cbd5e1; border-radius:10px; overflow:hidden;
        }}
        .pipeline-step {{
            position:relative; padding:.72rem .45rem; text-align:center; font-size:.82rem;
            font-weight:700; color:#64748b; background:#f8fafc; border-right:1px solid #cbd5e1;
        }}
        .pipeline-step:last-child {{ border-right:0; }}
        .pipeline-step.done {{ background:#ccfbf1; color:#115e59; }}
        .pipeline-step.current {{ background:#0f766e; color:white; }}
        @media (max-width: 760px) {{
            .pipeline-strip {{ grid-template-columns:1fr; }}
            .pipeline-step {{ border-right:0; border-bottom:1px solid #cbd5e1; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def stage_badge_html(stage: str) -> str:
    label = STAGE_LABELS.get(stage, stage.title())
    color = STAGE_COLORS.get(stage, TEAL_PRIMARY)
    return (
        f'<span class="tracking-stage-badge" style="background:{color};">{label}</span>'
    )


def tracking_card_html(
    *,
    title: str,
    company: str,
    stage: str,
    location: str = "",
) -> str:
    location_line = f'<div class="tracking-card-meta">{location}</div>' if location else ""
    return (
        f'<div class="tracking-card">'
        f'{stage_badge_html(stage)}'
        f'<div class="tracking-card-title">{title}</div>'
        f'<div class="tracking-card-meta">{company}</div>'
        f"{location_line}"
        f"</div>"
    )
