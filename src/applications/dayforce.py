"""Dayforce application-page inspection for the first application-agent case."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.jobs.board_discovery.playwright_client import PlaywrightBrowserClient


@dataclass(frozen=True)
class ApplicationField:
    section: str
    field_key: str
    label: str
    field_type: str = "text"
    required: bool = False
    options: tuple[str, ...] = ()
    position: int = 0


@dataclass(frozen=True)
class ApplicationInspection:
    provider: str
    application_url: str
    current_page: str
    fields: tuple[ApplicationField, ...] = field(default_factory=tuple)
    requires_account: bool = False
    privacy_consent_required: bool = False
    captcha_required: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


def supports_dayforce(url: str) -> bool:
    return urlparse(url).netloc.casefold().endswith("dayforcehcm.com")


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).replace("*", "").strip().rstrip(":")


def parse_dayforce_application(html: str, url: str) -> ApplicationInspection:
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    fields: list[ApplicationField] = []
    seen: set[str] = set()
    ignored = {"attachment", "language", "search", "cookie preferences"}

    controls = soup.select("input, textarea, select, [role='combobox']")
    for control in controls:
        control_type = str(control.get("type") or control.name or "text").casefold()
        if control_type in {"hidden", "submit", "button"}:
            continue
        label = str(control.get("aria-label") or control.get("placeholder") or "").strip()
        control_id = str(control.get("id") or "").strip()
        if not label and control_id:
            label_node = soup.find("label", attrs={"for": control_id})
            if label_node:
                label = label_node.get_text(" ", strip=True)
        label = _clean_label(label)
        if not label or label.casefold() in ignored:
            continue
        field_key = _key(label)
        if not field_key or field_key in seen:
            continue
        seen.add(field_key)
        required = (
            str(control.get("required") or "").casefold() in {"required", "true"}
            or str(control.get("aria-required") or "").casefold() == "true"
            or "*" in str(control.get("aria-label") or "")
        )
        options = tuple(
            _clean_label(option.get_text(" ", strip=True))
            for option in control.select("option")
            if _clean_label(option.get_text(" ", strip=True))
        )
        field_type = "select" if control.name == "select" or control.get("role") == "combobox" else control_type
        fields.append(
            ApplicationField(
                section="contact_details",
                field_key=field_key,
                label=label,
                field_type=field_type,
                required=required,
                options=options,
                position=len(fields) + 1,
            )
        )

    # Dayforce exposes these document controls as buttons rather than file inputs.
    fields.extend(
        (
            ApplicationField("resume", "resume", "Resume", "file", True, position=100),
            ApplicationField("cover_letter", "cover_letter", "Cover letter", "file", False, position=110),
        )
    )
    if "Additional Documents" in page_text:
        fields.append(
            ApplicationField("additional_documents", "additional_documents", "Additional documents", "file", False, position=120)
        )

    notes = (
        "Questionnaire fields are discovered after reviewed candidate information is entered and Next is pressed.",
        "Cover letter is optional on this page but included in the preparation workflow by default.",
    )
    return ApplicationInspection(
        provider="dayforce",
        application_url=url,
        current_page="candidate_info",
        fields=tuple(fields),
        requires_account="Create Account" in page_text and "Candidate Info" not in page_text,
        privacy_consent_required=(
            "I agree to the Privacy Statement" in page_text
            or "i agree to the privacy statement" in html.casefold()
        ),
        captcha_required="recaptcha" in html.casefold(),
        notes=notes,
    )


def inspect_dayforce_application(url: str) -> ApplicationInspection:
    if not supports_dayforce(url):
        raise ValueError("The first application-agent adapter supports Dayforce URLs only.")
    with PlaywrightBrowserClient(headless=True, delay_ms=0) as browser:
        result = browser.get_page_html(url, extra_wait_ms=2500)
    if result.blocked_reason:
        raise RuntimeError(f"Application page was blocked: {result.blocked_reason}")
    return parse_dayforce_application(result.html, result.final_url or url)
