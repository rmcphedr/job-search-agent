"""Batch company fit scoring CLI."""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field

import pandas as pd

from src.database.import_inventory import get_inventory_path
from src.llm.company_fit import score_company_safe
from src.llm.llm_client import LLMClientError, OllamaClient, load_llm_config
from src.llm.score_exports import company_result_to_row, upsert_company_fit_rows


@dataclass
class CompanyScoreSummary:
    companies_processed: int = 0
    companies_scored: int = 0
    cache_hits: int = 0
    errors: int = 0
    export_path: str = ""
    error_messages: list[str] = field(default_factory=list)


def _company_matches(name: str, company_filter: str) -> bool:
    target = company_filter.strip().lower()
    return name.strip().lower() == target or target in name.strip().lower()


def score_companies(
    *,
    limit: int | None = None,
    company: str | None = None,
    force_refresh: bool = False,
) -> CompanyScoreSummary:
    """Score companies from the inventory CSV and export results."""
    config = load_llm_config()
    batch_size = int(config.get("batch_size", 5))
    inventory_path = get_inventory_path()
    frame = pd.read_csv(inventory_path, dtype=str)
    summary = CompanyScoreSummary()
    export_rows: list[dict[str, object]] = []

    try:
        client = OllamaClient(config)
    except LLMClientError as exc:
        summary.errors += 1
        summary.error_messages.append(str(exc))
        return summary

    pending = 0
    for _, row in frame.iterrows():
        company_name = str(row.get("company_name", "")).strip()
        if not company_name:
            continue
        if company and not _company_matches(company_name, company):
            continue
        if limit is not None and summary.companies_processed >= limit:
            break

        summary.companies_processed += 1
        record = row.to_dict()
        result, error = score_company_safe(record, client=client, force_refresh=force_refresh)

        if error:
            summary.errors += 1
            summary.error_messages.append(f"{company_name}: {error}")
            continue

        if result is None:
            summary.errors += 1
            continue

        summary.companies_scored += 1
        export_rows.append(company_result_to_row(result))
        pending += 1

        if pending >= batch_size:
            path = upsert_company_fit_rows(export_rows)
            summary.export_path = str(path)
            export_rows.clear()
            pending = 0

    if export_rows:
        path = upsert_company_fit_rows(export_rows)
        summary.export_path = str(path)

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score companies for candidate fit using local Ollama.")
    parser.add_argument("--limit", type=int, default=None, help="Score at most N companies.")
    parser.add_argument("--company", type=str, default=None, help="Score one company by name.")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore cache and re-score with the LLM.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable informational logging.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    summary = score_companies(
        limit=args.limit,
        company=args.company,
        force_refresh=args.force_refresh,
    )

    print("Company fit scoring summary:")
    print(f"  companies processed: {summary.companies_processed}")
    print(f"  companies scored: {summary.companies_scored}")
    print(f"  errors: {summary.errors}")
    if summary.export_path:
        print(f"  export CSV: {summary.export_path}")
    if summary.error_messages:
        print("  error details:")
        for message in summary.error_messages[:10]:
            print(f"    - {message}")


if __name__ == "__main__":
    main()
