"""Parse structured job details from career page HTML."""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.jobs.job_url_utils import location_from_job_url, normalize_text

WORK_LOCATION_TYPES = frozenset({"remote", "hybrid", "on-site", "onsite", "on site"})
TEMPLATE_PLACEHOLDER_RE = re.compile(r"__[\w.]+__")
GEOGRAPHY_RE = re.compile(
    r"\b("
    r"[A-Z][a-zA-Z\s\.'\u00c0-\u024f-]{1,40},\s*"
    r"(?:[A-Z]{2}|[A-Z][a-zA-Z\s\.'\u00c0-\u024f-]{2,30})"
    r")\b"
)


def fix_text_encoding(text: str | None) -> str | None:
    if not text:
        return text
    if "â" in text or "Ã" in text:
        try:
            return text.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def _clean_scraped_text(text: str | None) -> str:
    if not text:
        return ""
    cleaned = unescape(text)
    cleaned = TEMPLATE_PLACEHOLDER_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return fix_text_encoding(cleaned) or ""


def _is_work_location_type(value: str | None) -> bool:
    if not value:
        return False
    return normalize_text(value) in WORK_LOCATION_TYPES


def _extract_geography_from_text(text: str) -> str | None:
    cleaned = _clean_scraped_text(text)
    if not cleaned or _is_work_location_type(cleaned):
        return None
    match = GEOGRAPHY_RE.search(cleaned)
    if match:
        return match.group(1).strip(" ,.")
    return None


def _parse_json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            objects.append(payload)
        elif isinstance(payload, list):
            objects.extend(item for item in payload if isinstance(item, dict))
    return objects


def _job_posting_from_json_ld(objects: list[dict[str, Any]]) -> dict[str, Any] | None:
    for obj in objects:
        obj_type = obj.get("@type")
        if obj_type == "JobPosting":
            return obj
        if isinstance(obj.get("@graph"), list):
            for node in obj["@graph"]:
                if isinstance(node, dict) and node.get("@type") == "JobPosting":
                    return node
    return None


def _location_from_json_ld(job_posting: dict[str, Any]) -> tuple[str | None, str | None]:
    geography = None
    location_type = None
    job_location = job_posting.get("jobLocation")
    locations = job_location if isinstance(job_location, list) else [job_location]

    for item in locations:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        if isinstance(address, dict):
            locality = _clean_scraped_text(str(address.get("addressLocality", "")))
            region = _clean_scraped_text(str(address.get("addressRegion", "")))
            country = _clean_scraped_text(str(address.get("addressCountry", "")))
            parts = [part for part in (locality, region) if part]
            if parts:
                geography = ", ".join(parts)
                break
            if country and not geography:
                geography = country

    if not geography:
        candidate = _clean_scraped_text(str(job_posting.get("jobLocation", "")))
        geography = _extract_geography_from_text(candidate)

    employment = job_posting.get("employmentType")
    if isinstance(employment, str) and _is_work_location_type(employment):
        location_type = employment.title()

    return geography, location_type


def _html_to_plain_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    lines = [_clean_scraped_text(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _parse_abbvie_widgets(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    geography = None
    location_type = None

    value_nodes = soup.select(".attrax-job-information-widget__freetext-field-value")
    for node in value_nodes:
        text = _clean_scraped_text(node.get_text(" ", strip=True))
        if not text or _is_work_location_type(text):
            continue
        if GEOGRAPHY_RE.search(text):
            geography = text
            break

    for label in soup.find_all("label", class_=re.compile("Worklocationtype", re.I)):
        wrapper = label.find_parent(class_=re.compile("Worklocationtype-wrapper", re.I))
        if wrapper is None:
            wrapper = label.find_next(class_=re.compile("Worklocationtype-wrapper", re.I))
        if wrapper is not None:
            value = _clean_scraped_text(wrapper.get_text(" ", strip=True))
            value = re.sub(r"work location type\s*:?\s*", "", value, flags=re.I).strip()
            if value:
                location_type = value.title()
            break

    if location_type is None:
        for node in soup.select("[class*='Worklocationtype-wrapper']"):
            value = _clean_scraped_text(node.get_text(" ", strip=True))
            if value and _is_work_location_type(value):
                location_type = value.title()
                break

    return geography, location_type


def parse_job_detail_from_html(html: str, url: str) -> dict[str, str | None]:
    """Parse title, geography location, work location type, and raw description."""
    soup = BeautifulSoup(html, "html.parser")
    json_ld_objects = _parse_json_ld_objects(soup)
    job_posting = _job_posting_from_json_ld(json_ld_objects)

    title = None
    if job_posting and job_posting.get("title"):
        title = _clean_scraped_text(str(job_posting["title"]))

    geography = location_from_job_url(url)
    location_type = None

    if job_posting:
        ld_geography, ld_type = _location_from_json_ld(job_posting)
        geography = geography or ld_geography
        location_type = location_type or ld_type

    domain = urlparse(url).netloc.lower()
    if "careers.abbvie.com" in domain:
        abbvie_geography, abbvie_type = _parse_abbvie_widgets(soup)
        geography = geography or abbvie_geography
        location_type = location_type or abbvie_type

    description_raw = None
    if job_posting and job_posting.get("description"):
        description_raw = _html_to_plain_text(str(job_posting["description"]))
    if not description_raw or len(description_raw) < 80:
        for selector in (
            ".jobad-companydescription",
            ".jobad-jobdescription",
            'div[class*="job-description"]',
            'div[class*="description"]',
            "main",
            "article",
        ):
            block = soup.select_one(selector)
            if block is not None:
                candidate = _html_to_plain_text(str(block))
                if candidate and len(candidate) > 80:
                    description_raw = candidate
                    break

    if not description_raw:
        body = soup.find("body")
        if body is not None:
            description_raw = _html_to_plain_text(str(body))

    description_raw = _clean_scraped_text(description_raw)
    if description_raw:
        description_raw = re.sub(r"\n{3,}", "\n\n", description_raw)

    return {
        "title": title,
        "location": geography,
        "location_type": location_type,
        "description_raw": description_raw or None,
        "url": url,
    }
