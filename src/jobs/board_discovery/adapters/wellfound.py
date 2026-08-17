"""Wellfound adapter (phase 2 — JS-heavy)."""

from __future__ import annotations

from src.jobs.board_discovery.adapters.stub import StubAdapter


class WellfoundAdapter(StubAdapter):
    source_id = "wellfound"
