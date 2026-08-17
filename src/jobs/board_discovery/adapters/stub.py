"""Stub adapter for boards not yet implemented."""

from __future__ import annotations

import logging

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.job_models import JobCandidate

logger = logging.getLogger(__name__)


class StubAdapter:
    source_id = "stub"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        logger.info(
            "Skipping board %s (%s): adapter=%s phase=%s — %s",
            source.source_id,
            source.name,
            source.adapter,
            source.phase,
            source.notes or "not implemented",
        )
        return []
