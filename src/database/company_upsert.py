"""Insert or resolve companies discovered from job board postings."""

from __future__ import annotations

import re
import sqlite3
from urllib.parse import urlparse

from src.discovery.link_utils import clean_url

BOARD_DISCOVERED_STATUS = "board_discovered"
PLACEHOLDER_DOMAIN = "unresolved.local"

_JOB_BOARD_DOMAINS: set[str] | None = None


def _load_job_board_domains() -> set[str]:
    global _JOB_BOARD_DOMAINS
    if _JOB_BOARD_DOMAINS is not None:
        return _JOB_BOARD_DOMAINS

    from src.jobs.board_discovery.config import load_board_sources_config

    config = load_board_sources_config()
    domains = {domain.lower().strip() for domain in config.job_board_domains if domain.strip()}
    _JOB_BOARD_DOMAINS = domains
    return domains


def slugify_company_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unknown-company"


def is_job_board_host(hostname: str) -> bool:
    host = hostname.lower().removeprefix("www.")
    domains = _load_job_board_domains()
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def derive_website_from_job_url(url: str | None) -> str | None:
    if not url:
        return None
    cleaned = clean_url(url)
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if not parsed.netloc or is_job_board_host(parsed.netloc):
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def placeholder_website(company_name: str) -> str:
    return f"https://{PLACEHOLDER_DOMAIN}/{slugify_company_name(company_name)}"


def resolve_company_id(connection: sqlite3.Connection, company_name: str) -> int | None:
    row = connection.execute(
        "SELECT company_id FROM companies WHERE company_name = ? COLLATE NOCASE LIMIT 1;",
        (company_name.strip(),),
    ).fetchone()
    if row is not None:
        return int(row["company_id"])
    return None


def upsert_company_from_job(
    connection: sqlite3.Connection,
    *,
    company_name: str,
    job_url: str | None = None,
    location: str | None = None,
) -> int:
    """Return company_id, creating a placeholder company row when needed."""
    cleaned_name = company_name.strip()
    if not cleaned_name:
        raise ValueError("company_name must be non-empty.")

    existing_id = resolve_company_id(connection, cleaned_name)
    if existing_id is not None:
        return existing_id

    website = derive_website_from_job_url(job_url) or placeholder_website(cleaned_name)

    existing_by_website = connection.execute(
        "SELECT company_id FROM companies WHERE website = ? LIMIT 1;",
        (website,),
    ).fetchone()
    if existing_by_website is not None:
        return int(existing_by_website["company_id"])

    cursor = connection.execute(
        """
        INSERT INTO companies (
            company_name,
            website,
            location,
            hiring_status
        ) VALUES (?, ?, ?, ?);
        """,
        (cleaned_name, website, location, BOARD_DISCOVERED_STATUS),
    )
    return int(cursor.lastrowid)
