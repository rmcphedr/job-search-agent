"""Profile / Settings view for the Streamlit dashboard."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import yaml

from src.database.db import get_project_root
from src.ui.data_loader import load_yaml_config


def render_profile_view() -> None:
    """Render read-only project configuration files."""
    st.header("Profile / Settings")
    st.caption("Read-only view of keyword and scoring configuration.")

    config_files = (
        ("Job keywords", get_project_root() / "config" / "job_keywords.yaml"),
        ("Scoring", get_project_root() / "config" / "scoring.yaml"),
        ("Settings", get_project_root() / "config" / "settings.yaml"),
    )

    for label, path in config_files:
        st.subheader(label)
        _render_yaml_block(path)


def _render_yaml_block(path: Path) -> None:
    if not path.exists():
        st.warning(f"Config file not found: `{path}`")
        return

    data = load_yaml_config(path)
    if not data:
        st.info(f"`{path.name}` is empty or could not be parsed.")
        return

    yaml_text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    st.code(yaml_text, language="yaml")
