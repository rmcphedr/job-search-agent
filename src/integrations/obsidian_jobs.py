"""Import Obsidian job clippings from the sibling resume pipeline."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.database.db import get_connection
from src.database.company_upsert import upsert_company_from_job
from src.database.migrate import apply_migrations
from src.integrations.resume_pipeline import get_resume_pipeline_root
from src.jobs.job_url_utils import normalize_job_url


@dataclass(frozen=True)
class ObsidianJob:
    title: str
    company_name: str
    url: str
    description: str
    source_path: Path
    created: str | None = None


@dataclass
class ObsidianSyncResult:
    scanned: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    companies_created: int = 0


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text.strip()
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.DOTALL)
    if not match:
        return {}, text.strip()
    loaded = yaml.safe_load(match.group(1)) or {}
    return (loaded if isinstance(loaded, dict) else {}), text[match.end() :].strip()


def parse_obsidian_clipping(path: Path) -> ObsidianJob:
    metadata, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    combined_title = str(metadata.get("title") or "").strip()
    if "|" in combined_title:
        title, company_name = (part.strip() for part in combined_title.rsplit("|", 1))
    else:
        title = combined_title
        company_name = _infer_company_name(metadata, body)
    url = normalize_job_url(str(metadata.get("source") or "")) or ""
    if not title or not company_name or not url or not body:
        raise ValueError("clipping requires title, company, source URL, and body")
    created = metadata.get("created")
    return ObsidianJob(
        title=title,
        company_name=company_name,
        url=url,
        description=body,
        source_path=path.resolve(),
        created=str(created) if created else None,
    )


def _infer_company_name(metadata: dict[str, Any], body: str) -> str:
    """Infer an employer when the clipper omits it from the title."""
    description = str(metadata.get("description") or "").strip()
    patterns = (
        (description, r"\b(?:join|at)\s+(.+?)\s+as\s+"),
        (body[:500], r"^At\s+([^,\n]+),"),
        (body[:500], r"\bJoin\s+([^,.\n]+?)\s+(?:in|as)\s+"),
    )
    for text, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _title_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _find_existing_job(connection, job: ObsidianJob) -> int | None:
    row = connection.execute(
        "SELECT job_id FROM job_postings WHERE url = ? LIMIT 1", (job.url,)
    ).fetchone()
    if row:
        return int(row["job_id"])
    rows = connection.execute(
        """SELECT j.job_id, j.title FROM job_postings AS j
           JOIN companies AS c ON c.company_id = j.company_id
           WHERE c.company_name = ? COLLATE NOCASE""",
        (job.company_name,),
    ).fetchall()
    target = _title_key(job.title)
    for existing in rows:
        if _title_key(str(existing["title"])) == target:
            return int(existing["job_id"])
    return None


def sync_obsidian_clippings(
    *, pipeline_root: Path | None = None, dry_run: bool = False
) -> ObsidianSyncResult:
    """Upsert full clipped descriptions into the canonical job database."""
    clipping_dir = (pipeline_root or get_resume_pipeline_root()) / "Clippings"
    result = ObsidianSyncResult()
    if not clipping_dir.exists():
        return result
    connection = get_connection()
    try:
        apply_migrations(connection)
        for path in sorted(clipping_dir.glob("*.md")):
            result.scanned += 1
            try:
                job = parse_obsidian_clipping(path)
            except (OSError, ValueError, yaml.YAMLError):
                result.skipped += 1
                continue
            company = connection.execute(
                "SELECT company_id FROM companies WHERE company_name = ? COLLATE NOCASE LIMIT 1",
                (job.company_name,),
            ).fetchone()
            if company is None:
                company_id = upsert_company_from_job(
                    connection,
                    company_name=job.company_name,
                    job_url=job.url,
                    location=None,
                )
                result.companies_created += 1
            else:
                company_id = int(company["company_id"])
            existing_id = _find_existing_job(connection, job)
            source_ref = str(job.source_path)
            checked_at = datetime.now(timezone.utc).isoformat()
            if existing_id is None:
                connection.execute(
                    """INSERT INTO job_postings (
                         company_id, title, url, description, date_found, active,
                         source_board, description_status, description_source,
                         description_source_url, description_checked_at)
                       VALUES (?, ?, ?, ?, ?, 1, 'obsidian_clip', 'enriched',
                               'obsidian_clip', ?, ?)""",
                    (company_id, job.title, job.url, job.description,
                     job.created, source_ref, checked_at),
                )
                result.inserted += 1
                continue
            existing = connection.execute(
                "SELECT description, description_source_url FROM job_postings WHERE job_id = ?",
                (existing_id,),
            ).fetchone()
            if (str(existing["description"] or "") == job.description
                    and str(existing["description_source_url"] or "") == source_ref):
                result.unchanged += 1
                continue
            connection.execute(
                """UPDATE job_postings
                   SET title = ?, url = ?, description = ?, active = 1,
                       source_board = 'obsidian_clip', description_status = 'enriched',
                       description_source = 'obsidian_clip', description_source_url = ?,
                       description_checked_at = ?, description_error = NULL,
                       fit_score = NULL, fit_reason = NULL, fit_details = NULL, evaluated_at = NULL
                   WHERE job_id = ?""",
                (job.title, job.url, job.description, source_ref, checked_at, existing_id),
            )
            result.updated += 1
        connection.rollback() if dry_run else connection.commit()
    finally:
        connection.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Obsidian job clippings into SQLite")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = sync_obsidian_clippings(dry_run=args.dry_run)
    print(f"Obsidian sync: {result.scanned} scanned, {result.inserted} inserted, "
          f"{result.updated} updated, {result.unchanged} unchanged, {result.skipped} skipped, "
          f"{result.companies_created} companies created")


if __name__ == "__main__":
    main()
