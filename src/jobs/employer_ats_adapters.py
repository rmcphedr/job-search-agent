"""API-first adapters for employer-hosted applicant tracking systems."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.discovery.fetch import get_request_timeout, get_user_agent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ATSJob:
    """Provider-neutral listing returned by an ATS adapter."""

    title: str
    url: str | None
    location: str | None = None
    description: str | None = None
    date_posted: str | None = None


class ATSAdapter(Protocol):
    provider: str

    def extract(self, url: str, html: str) -> list[ATSJob]: ...


def _text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = BeautifulSoup(str(value), "html.parser").get_text("\n", strip=True)
    return rendered or None


def _get_json(url: str) -> Any:
    response = requests.get(
        url,
        headers={"User-Agent": get_user_agent(), "Accept": "application/json"},
        timeout=get_request_timeout(),
    )
    response.raise_for_status()
    return response.json()


class GreenhouseAdapter:
    provider = "greenhouse"

    @staticmethod
    def board_token(url: str, html: str) -> str | None:
        patterns = (
            r"boards-api\.greenhouse\.io/v1/boards/([^/?#\"'\s]+)",
            r"(?:boards|job-boards)\.greenhouse\.io/([^/?#\"'\s]+)",
            r"\bfor=([^&\"'\s]+)",
            r"data-board-token=[\"']([^\"']+)[\"']",
        )
        for source in (url, html):
            for pattern in patterns:
                match = re.search(pattern, source, flags=re.I)
                if match and match.group(1).lower() not in {"embed", "jobs", "boards"}:
                    return unquote(match.group(1))
        return None

    def extract(self, url: str, html: str) -> list[ATSJob]:
        token = self.board_token(url, html)
        if not token:
            return []
        payload = _get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        )
        return [
            ATSJob(
                title=str(job.get("title") or "").strip(),
                url=job.get("absolute_url"),
                location=(job.get("location") or {}).get("name")
                if isinstance(job.get("location"), dict)
                else job.get("location"),
                description=_text(job.get("content")),
                date_posted=job.get("updated_at"),
            )
            for job in payload.get("jobs", [])
            if job.get("title")
        ]


class LeverAdapter:
    provider = "lever"

    @staticmethod
    def site_token(url: str, html: str) -> str | None:
        for source in (url, html):
            match = re.search(r"(?:jobs|api)\.lever\.co/(?:v0/postings/)?([^/?#\"'\s]+)", source, re.I)
            if match and match.group(1).lower() not in {"embed", "postings"}:
                return unquote(match.group(1))
        return None

    def extract(self, url: str, html: str) -> list[ATSJob]:
        token = self.site_token(url, html)
        if not token:
            return []
        payload = _get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
        jobs = payload if isinstance(payload, list) else []
        return [
            ATSJob(
                title=str(job.get("text") or "").strip(),
                url=job.get("hostedUrl") or job.get("applyUrl"),
                location=(job.get("categories") or {}).get("location"),
                description=_text(job.get("descriptionPlain") or job.get("description")),
            )
            for job in jobs
            if job.get("text")
        ]


class AshbyAdapter:
    provider = "ashby"

    @staticmethod
    def board_token(url: str, html: str) -> str | None:
        for source in (url, html):
            match = re.search(r"jobs\.ashbyhq\.com/([^/?#\"'\s]+)", source, re.I)
            if match:
                return unquote(match.group(1))
        return None

    def extract(self, url: str, html: str) -> list[ATSJob]:
        token = self.board_token(url, html)
        if not token:
            return []
        payload = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
        return [
            ATSJob(
                title=str(job.get("title") or "").strip(),
                url=job.get("jobUrl") or job.get("applyUrl"),
                location=job.get("location"),
                description=_text(job.get("descriptionHtml") or job.get("descriptionPlain")),
                date_posted=job.get("publishedAt"),
            )
            for job in payload.get("jobs", [])
            if job.get("title") and job.get("isListed", True)
        ]


class WorkdayAdapter:
    provider = "workday"
    page_size = 20
    max_pages = 10

    @staticmethod
    def coordinates(url: str) -> tuple[str, str, str] | None:
        parsed = urlparse(url)
        if "workdayjobs.com" not in parsed.netloc.lower():
            return None
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
            parts.pop(0)
        if not parts:
            return None
        tenant = parsed.netloc.split(".")[0]
        return parsed.netloc, tenant, parts[0]

    def extract(self, url: str, html: str) -> list[ATSJob]:
        coordinates = self.coordinates(url)
        if not coordinates:
            match = re.search(r"https?://[^\"'\s]+(?:my)?workdayjobs\.com/[^\"'\s]+", html, re.I)
            coordinates = self.coordinates(match.group(0)) if match else None
        if not coordinates:
            return []
        host, tenant, site = coordinates
        endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        jobs: list[ATSJob] = []
        offset = 0
        for _ in range(self.max_pages):
            response = requests.post(
                endpoint,
                headers={"User-Agent": get_user_agent(), "Accept": "application/json"},
                json={"appliedFacets": {}, "limit": self.page_size, "offset": offset, "searchText": ""},
                timeout=get_request_timeout(),
            )
            response.raise_for_status()
            payload = response.json()
            postings = payload.get("jobPostings", [])
            for job in postings:
                external_path = job.get("externalPath")
                jobs.append(
                    ATSJob(
                        title=str(job.get("title") or "").strip(),
                        url=urljoin(f"https://{host}/{site}/", str(external_path).lstrip("/"))
                        if external_path
                        else None,
                        location=job.get("locationsText"),
                        description=_text("\n".join(job.get("bulletFields") or [])),
                        date_posted=job.get("postedOn"),
                    )
                )
            offset += len(postings)
            if not postings or offset >= int(payload.get("total") or offset):
                break
        return [job for job in jobs if job.title]


ADAPTERS: dict[str, ATSAdapter] = {
    adapter.provider: adapter
    for adapter in (GreenhouseAdapter(), LeverAdapter(), AshbyAdapter(), WorkdayAdapter())
}


def extract_ats_jobs(provider: str, url: str, html: str) -> list[ATSJob]:
    """Run an ATS API adapter; failures are recoverable by the HTML extractor."""
    adapter = ADAPTERS.get(provider)
    if adapter is None:
        return []
    try:
        return adapter.extract(url, html)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        logger.warning("%s adapter failed for %s: %s", provider, url, exc)
        return []
