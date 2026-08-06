"""Mila careers adapter via Workable widget API."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urljoin

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import build_candidate
from src.jobs.job_models import JobCandidate

logger = logging.getLogger(__name__)

DEFAULT_ACCOUNT_SLUG = "mila-2"
DEFAULT_COMPANY_NAME = "Mila - Quebec AI Institute"


def _widget_api_url(source: BoardSource) -> str:
    slug = source.search_params.get("account_slug", DEFAULT_ACCOUNT_SLUG)
    base = source.base_url.rstrip("/")
    path = source.search_path or f"/api/v1/widget/accounts/{slug}"
    if "{account_slug}" in path:
        path = path.format(account_slug=slug)
    return urljoin(base + "/", path.lstrip("/"))


def _format_location(job: dict[str, Any]) -> str | None:
    city = str(job.get("city") or "").strip()
    state = str(job.get("state") or "").strip()
    country = str(job.get("country") or "").strip()
    parts = [part for part in (city, state, country) if part]
    return ", ".join(parts) if parts else None


def parse_mila_workable_payload(
    payload: dict[str, Any],
    *,
    source: BoardSource,
    search_url: str,
    company_name: str | None = None,
) -> list[JobCandidate]:
    employer = company_name or str(payload.get("name") or DEFAULT_COMPANY_NAME).strip()
    jobs_raw = payload.get("jobs")
    if not isinstance(jobs_raw, list):
        return []

    results: list[JobCandidate] = []
    seen_urls: set[str] = set()

    for job in jobs_raw:
        if not isinstance(job, dict):
            continue
        title = str(job.get("title") or "").strip()
        url = str(job.get("shortlink") or job.get("url") or "").strip()
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)

        candidate = build_candidate(
            source=source,
            company_name=employer,
            title=title,
            location=_format_location(job),
            url=url,
            description=None,
            search_url=search_url,
        )
        if candidate is not None:
            results.append(candidate)

    return results


class MilaWorkableAdapter:
    source_id = "mila"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        del query, location, max_pages
        api_url = _widget_api_url(source)

        try:
            client._throttle()
            response = client.session.get(api_url, timeout=client.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Mila Workable API returned invalid JSON from %s: %s", api_url, exc)
            return []
        except Exception as exc:
            logger.warning("Mila Workable API fetch failed for %s: %s", api_url, exc)
            return []

        if not isinstance(payload, dict):
            logger.warning("Mila Workable API payload must be an object: %s", api_url)
            return []

        return parse_mila_workable_payload(payload, source=source, search_url=api_url)

    def _parse_listing(
        self,
        html: str,
        *,
        source: BoardSource,
        search_url: str,
    ) -> list[JobCandidate]:
        del html
        return []
