"""Playwright settings loaded from config/settings.yaml and board overrides."""

from __future__ import annotations

from typing import Any

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import _scraping_settings

VALID_WAIT_UNTIL = frozenset({"commit", "domcontentloaded", "load", "networkidle"})


def get_playwright_defaults() -> dict[str, Any]:
    scraping = _scraping_settings()
    playwright = scraping.get("playwright", {})
    if not isinstance(playwright, dict):
        playwright = {}

    wait_until = str(playwright.get("wait_until", scraping.get("playwright_wait_until", "domcontentloaded")))
    if wait_until not in VALID_WAIT_UNTIL:
        wait_until = "domcontentloaded"

    return {
        "headless": bool(playwright.get("headless", scraping.get("playwright_headless", True))),
        "timeout_ms": int(playwright.get("timeout_ms", scraping.get("playwright_timeout_ms", 45000))),
        "wait_until": wait_until,
        "extra_wait_ms": int(playwright.get("extra_wait_ms", 1500)),
        "viewport_width": int(playwright.get("viewport_width", 1280)),
        "viewport_height": int(playwright.get("viewport_height", 900)),
    }


def resolve_board_playwright(board: BoardSource, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge global Playwright defaults with per-board overrides from search_params."""
    base = dict(defaults or get_playwright_defaults())
    params = board.search_params

    if "playwright_wait_until" in params:
        wait = params["playwright_wait_until"]
        if wait in VALID_WAIT_UNTIL:
            base["wait_until"] = wait

    if "playwright_extra_wait_ms" in params:
        try:
            base["extra_wait_ms"] = int(params["playwright_extra_wait_ms"])
        except (TypeError, ValueError):
            pass

    if "playwright_timeout_ms" in params:
        try:
            base["timeout_ms"] = int(params["playwright_timeout_ms"])
        except (TypeError, ValueError):
            pass

    base["wait_selector"] = board.wait_selector
    return base


def detect_blocked_page(html: str) -> str | None:
    """Return a short reason when HTML looks like a bot block or empty shell."""
    lowered = html.lower()
    if "geo.captcha-delivery.com" in lowered:
        return "datadome_captcha"
    if len(html) < 4000 and "captcha-delivery.com" in lowered:
        return "captcha_delivery"
    if "cf-browser-verification" in lowered or "checking your browser" in lowered:
        return "cloudflare_challenge"
    if "indeed.com/recaptcha" in lowered or ("hcaptcha" in lowered and "indeed" in lowered):
        return "indeed_captcha"
    if "indeed.com" in lowered and "captcha" in lowered and "job_seen_beacon" not in lowered:
        return "indeed_captcha"
    if len(html) < 3000 and "<iframe" in lowered and "captcha" in lowered:
        return "captcha_iframe"
    return None
