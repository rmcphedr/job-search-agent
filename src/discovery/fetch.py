"""HTTP fetching utilities for directory discovery."""

from __future__ import annotations

import logging

import requests

from src.database.db import load_settings

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "job-search-agent/0.1"
DEFAULT_TIMEOUT = 20


def get_user_agent() -> str:
    """Return the configured scraping user agent, with a safe fallback."""
    try:
        settings = load_settings()
        scraping = settings.get("scraping", {})
        if isinstance(scraping, dict):
            user_agent = scraping.get("user_agent")
            if isinstance(user_agent, str) and user_agent.strip():
                return user_agent.strip()
    except RuntimeError:
        pass
    return DEFAULT_USER_AGENT


def get_request_timeout(default: int = DEFAULT_TIMEOUT) -> int:
    """Return the configured request timeout in seconds."""
    try:
        settings = load_settings()
        scraping = settings.get("scraping", {})
        if isinstance(scraping, dict):
            timeout = scraping.get("request_timeout_seconds")
            if isinstance(timeout, int) and timeout > 0:
                return timeout
    except RuntimeError:
        pass
    return default


def fetch_url(url: str, timeout: int | None = None) -> tuple[int, str]:
    """
    Fetch a URL and return (status_code, response_text).

    On network or request errors, returns (0, "") and logs the failure.
    """
    request_timeout = timeout if timeout is not None else get_request_timeout()
    headers = {"User-Agent": get_user_agent()}

    try:
        response = requests.get(url, headers=headers, timeout=request_timeout)
        return response.status_code, response.text
    except requests.Timeout:
        logger.warning("Timeout fetching %s after %ss", url, request_timeout)
        return 0, ""
    except requests.RequestException as exc:
        logger.warning("Request failed for %s: %s", url, exc)
        return 0, ""
