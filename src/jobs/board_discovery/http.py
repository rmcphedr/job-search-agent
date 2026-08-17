"""HTTP utilities for board discovery."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import requests

from src.database.db import get_project_root, load_settings

logger = logging.getLogger(__name__)

PERSISTENT_ERROR_MARKERS = (
    "403 Client Error",
    "SSLError",
    "NameResolutionError",
    "Connection refused",
)


def is_persistent_board_error(exc: BaseException) -> bool:
    """Return True when retrying the same board is unlikely to succeed."""
    message = str(exc)
    return any(marker in message for marker in PERSISTENT_ERROR_MARKERS)


def _scraping_settings() -> dict[str, Any]:
    settings = load_settings()
    scraping = settings.get("scraping", {})
    return scraping if isinstance(scraping, dict) else {}


def get_user_agent() -> str:
    return str(
        _scraping_settings().get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
    )


def get_accept_language() -> str:
    return str(_scraping_settings().get("accept_language", "en-CA,en;q=0.9"))


def get_timeout_seconds(default: float = 15.0) -> float:
    value = _scraping_settings().get("request_timeout_seconds", default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_cache_dir() -> Path:
    settings = load_settings()
    paths = settings.get("paths", {})
    if isinstance(paths, dict) and paths.get("cache"):
        return get_project_root() / str(paths["cache"]) / "board"
    return get_project_root() / "data" / "cache" / "board"


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": get_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": get_accept_language(),
        }
    )
    return session


class BoardHttpClient:
    """Rate-limited HTTP client for job board adapters."""

    def __init__(
        self,
        *,
        delay_ms: int = 1500,
        timeout_seconds: float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.delay_ms = delay_ms
        self.timeout_seconds = timeout_seconds or get_timeout_seconds()
        self.session = session or build_session()
        self._last_request_at = 0.0
        self._html_cache: dict[str, tuple[str, str]] = {}

    def _cache_key(self, url: str, params: dict[str, str] | None) -> str:
        if not params:
            return url
        query = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
        return f"{url}?{query}"

    def _throttle(self) -> None:
        if self.delay_ms <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait_seconds = (self.delay_ms / 1000.0) - elapsed
        if wait_seconds > 0:
            time.sleep(wait_seconds)

    def get(self, url: str, *, params: dict[str, str] | None = None) -> str:
        self._throttle()
        try:
            response = self.session.get(url, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Board fetch failed for %s: %s", url, exc)
            raise
        finally:
            self._last_request_at = time.monotonic()
        return response.text

    def get_with_url(self, url: str, *, params: dict[str, str] | None = None) -> tuple[str, str]:
        """Fetch HTML and return (html, final_url after redirects)."""
        cache_key = self._cache_key(url, params)
        cached = self._html_cache.get(cache_key)
        if cached is not None:
            return cached

        self._throttle()
        try:
            response = self.session.get(url, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Board fetch failed for %s: %s", url, exc)
            raise
        finally:
            self._last_request_at = time.monotonic()
        result = (response.text, str(response.url))
        self._html_cache[cache_key] = result
        return result
