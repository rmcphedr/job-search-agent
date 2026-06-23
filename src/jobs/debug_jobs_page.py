"""Debug career page job extraction for a single company."""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import pandas as pd

from src.database.db import get_project_root
from src.database.import_inventory import get_inventory_path
from src.discovery.link_utils import clean_url, normalize_url
from src.jobs.filter_jobs import filter_jobs, score_job
from src.jobs.job_extractors import detect_career_provider, extract_jobs_from_career_page, fetch_page
from src.jobs.job_url_utils import looks_like_job_link

logger = logging.getLogger(__name__)


def _safe_company_filename(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip().lower())
    return cleaned.strip("_") or "company"


def debug_jobs_page(company_name: str, output_dir: Path | None = None) -> None:
    frame = pd.read_csv(get_inventory_path(), dtype=str)
    matches = frame[
        frame["company_name"].fillna("").str.lower().str.contains(company_name.strip().lower())
    ]
    if matches.empty:
        raise ValueError(f"No company matched {company_name!r}")

    row = matches.iloc[0]
    name = str(row["company_name"]).strip()
    career_page = clean_url(str(row.get("career_page", "")))
    if not career_page:
        raise ValueError(f"{name} does not have a valid career_page")

    status_code, final_url, html = fetch_page(career_page)
    provider = detect_career_provider(final_url, html) if html else "generic_html"

    print(f"Company: {name}")
    print(f"Career page: {career_page}")
    print(f"Final URL: {final_url}")
    print(f"Detected provider: {provider}")
    print(f"HTTP status: {status_code}")

    soup_links = []
    if html:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        page_title = soup.title.string.strip() if soup.title and soup.title.string else ""
        print(f"Page title: {page_title}")

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href"))
            text = anchor.get_text(" ", strip=True)
            absolute = normalize_url(final_url, href)
            if absolute and looks_like_job_link(text, href):
                soup_links.append({"text": text, "url": absolute})

    print(f"Total career/job-like links: {len(soup_links)}")
    print("First 50 career/job-like links:")
    for index, link in enumerate(soup_links[:50], start=1):
        print(f"  {index:>2}. {link['text'][:70]} -> {link['url']}")

    extraction = extract_jobs_from_career_page(
        career_page,
        company_name=name,
        company_id=int(row["company_id"]) if str(row.get("company_id", "")).isdigit() else None,
        enrich_details=False,
    )
    raw_jobs = extraction["jobs"]
    filtered_jobs = filter_jobs(raw_jobs)
    filtered_hashes = {
        job.content_hash or f"{job.title}|{job.url}" for job in filtered_jobs
    }

    print("\nFirst 10 extracted job candidates (before filtering):")
    for index, job in enumerate(raw_jobs[:10], start=1):
        score, matched = score_job(job)
        print(
            f"  {index:>2}. {job.title} | url={job.url} | score={score:.2f} | matched={matched}"
        )

    print("\nFirst 10 filtered job candidates:")
    for index, job in enumerate(filtered_jobs[:10], start=1):
        print(
            f"  {index:>2}. {job.title} | url={job.url} | score={job.keyword_score:.2f}"
        )

    out_dir = output_dir or get_project_root() / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"debug_jobs_{_safe_company_filename(name)}.csv"

    rows = []
    for job in raw_jobs[:50]:
        score, matched = score_job(job)
        rows.append(
            {
                "company_name": name,
                "career_page": career_page,
                "provider": provider,
                "title": job.title,
                "url": job.url,
                "location": job.location,
                "keyword_score": score,
                "matched_keywords": "; ".join(matched),
                "filtered": (job.content_hash or f"{job.title}|{job.url}") in filtered_hashes,
            }
        )
    pd.DataFrame(rows).to_csv(output_path, index=False)
    print(f"\nSaved debug output to {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Debug job extraction for one company.")
    parser.add_argument("--company", required=True, help="Company name to debug.")
    parser.add_argument("--verbose", action="store_true", help="Enable informational logging.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    try:
        debug_jobs_page(args.company)
    except ValueError as exc:
        raise SystemExit(f"Debug failed: {exc}") from exc


if __name__ == "__main__":
    main()
