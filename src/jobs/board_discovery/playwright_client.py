"""Optional Playwright browser client for anti-bot job boards."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from src.jobs.board_discovery.http import build_session, get_timeout_seconds

logger = logging.getLogger(__name__)

_PLAYWRIGHT_AVAILABLE: bool | None = None


def playwright_available() -> bool:
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is not None:
        return _PLAYWRIGHT_AVAILABLE
    try:
        import playwright  # noqa: F401

        _PLAYWRIGHT_AVAILABLE = True
    except ImportError:
        _PLAYWRIGHT_AVAILABLE = False
    return _PLAYWRIGHT_AVAILABLE


@dataclass
class PlaywrightFetchResult:
    html: str
    final_url: str


@dataclass
class PlaywrightBrowserClient:
    """Shared Playwright browser for phase-3 board adapters."""

    headless: bool = True
    timeout_ms: int = 30000
    delay_ms: int = 1500
    _playwright: Any = field(default=None, repr=False)
    _browser: Any = field(default=None, repr=False)
    _context: Any = field(default=None, repr=False)
    _html_cache: dict[str, PlaywrightFetchResult] = field(default_factory=dict, repr=False)

    def __enter__(self) -> PlaywrightBrowserClient:
        if not playwright_available():
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )
        from playwright.sync_api import sync_playwright

        session = build_session()
        user_agent = session.headers.get("User-Agent", "")
        accept_language = session.headers.get("Accept-Language", "en-CA,en;q=0.9")

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent=user_agent,
            locale="en-CA",
            extra_http_headers={"Accept-Language": accept_language},
        )
        self._context.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._context = None
        self._browser = None
        self._playwright = None

    def _cache_key(self, url: str, params: dict[str, str] | None) -> str:
        if not params:
            return url
        return f"{url}?{urlencode(sorted(params.items()))}"

    def get_page_html(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        wait_selector: str | None = None,
    ) -> PlaywrightFetchResult:
        if self._context is None:
            raise RuntimeError("PlaywrightBrowserClient is not started. Use it as a context manager.")

        cache_key = self._cache_key(url, params)
        cached = self._html_cache.get(cache_key)
        if cached is not None:
            return cached

        target = cache_key
        page = self._context.new_page()
        try:
            page.goto(target, wait_until="networkidle", timeout=self.timeout_ms)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=self.timeout_ms)
                except Exception as exc:
                    logger.debug("Selector %s not found on %s: %s", wait_selector, target, exc)
            html = page.content()
            result = PlaywrightFetchResult(html=html, final_url=page.url)
        finally:
            page.close()

        self._html_cache[cache_key] = result
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        return result


def default_timeout_ms() -> int:
    return int(get_timeout_seconds() * 1000)
