"""Optional Playwright browser client for anti-bot job boards."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import build_session
from src.jobs.board_discovery.playwright_config import (
    detect_blocked_page,
    get_playwright_defaults,
    resolve_board_playwright,
)

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
    blocked_reason: str | None = None


@dataclass
class PlaywrightBrowserClient:
    """Shared Playwright browser for phase-3 board adapters."""

    headless: bool | None = None
    timeout_ms: int | None = None
    delay_ms: int = 1500
    wait_until: str | None = None
    extra_wait_ms: int | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None
    _playwright: Any = field(default=None, repr=False)
    _browser: Any = field(default=None, repr=False)
    _context: Any = field(default=None, repr=False)
    _html_cache: dict[str, PlaywrightFetchResult] = field(default_factory=dict, repr=False)
    _defaults: dict[str, Any] = field(default_factory=get_playwright_defaults, repr=False)

    def _resolved(self) -> dict[str, Any]:
        defaults = self._defaults
        return {
            "headless": self.headless if self.headless is not None else defaults["headless"],
            "timeout_ms": self.timeout_ms if self.timeout_ms is not None else defaults["timeout_ms"],
            "wait_until": self.wait_until or defaults["wait_until"],
            "extra_wait_ms": self.extra_wait_ms if self.extra_wait_ms is not None else defaults["extra_wait_ms"],
            "viewport_width": self.viewport_width if self.viewport_width is not None else defaults["viewport_width"],
            "viewport_height": self.viewport_height if self.viewport_height is not None else defaults["viewport_height"],
        }

    def __enter__(self) -> PlaywrightBrowserClient:
        if not playwright_available():
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )
        from playwright.sync_api import sync_playwright

        settings = self._resolved()
        session = build_session()
        user_agent = session.headers.get("User-Agent", "")
        accept_language = session.headers.get("Accept-Language", "en-CA,en;q=0.9")

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=settings["headless"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=user_agent,
            locale="en-CA",
            timezone_id="America/Toronto",
            viewport={
                "width": settings["viewport_width"],
                "height": settings["viewport_height"],
            },
            extra_http_headers={"Accept-Language": accept_language},
        )
        self._context.set_default_timeout(settings["timeout_ms"])
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
        wait_until: str | None = None,
        extra_wait_ms: int | None = None,
        timeout_ms: int | None = None,
    ) -> PlaywrightFetchResult:
        if self._context is None:
            raise RuntimeError("PlaywrightBrowserClient is not started. Use it as a context manager.")

        settings = self._resolved()
        cache_key = self._cache_key(url, params)
        cached = self._html_cache.get(cache_key)
        if cached is not None:
            return cached

        target = cache_key
        page = self._context.new_page()
        try:
            page.goto(
                target,
                wait_until=wait_until or settings["wait_until"],
                timeout=timeout_ms or settings["timeout_ms"],
            )
            resolved_wait = extra_wait_ms if extra_wait_ms is not None else settings["extra_wait_ms"]
            if resolved_wait > 0:
                page.wait_for_timeout(resolved_wait)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms or settings["timeout_ms"])
                except Exception as exc:
                    logger.debug("Selector %s not found on %s: %s", wait_selector, target, exc)
            html = page.content()
            blocked_reason = detect_blocked_page(html)
            result = PlaywrightFetchResult(html=html, final_url=page.url, blocked_reason=blocked_reason)
        finally:
            page.close()

        self._html_cache[cache_key] = result
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        return result

    def get_page_html_for_board(
        self,
        url: str,
        *,
        params: dict[str, str] | None,
        board: BoardSource,
    ) -> PlaywrightFetchResult:
        board_settings = resolve_board_playwright(board, self._resolved())
        return self.get_page_html(
            url,
            params=params,
            wait_selector=board_settings.get("wait_selector"),
            wait_until=board_settings.get("wait_until"),
            extra_wait_ms=board_settings.get("extra_wait_ms"),
            timeout_ms=board_settings.get("timeout_ms"),
        )


def default_timeout_ms() -> int:
    return int(get_playwright_defaults()["timeout_ms"])
