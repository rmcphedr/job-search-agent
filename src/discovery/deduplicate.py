"""Cross-source deduplication for discovered company candidates."""

from __future__ import annotations

from rapidfuzz import fuzz

from src.discovery.link_utils import get_domain, is_external_url, normalize_company_key
from src.discovery.models import CompanyCandidate

NAME_SIMILARITY_THRESHOLD = 88


def _dedupe_key(candidate: CompanyCandidate) -> str:
    source_domain = get_domain(candidate.source_url) or ""
    website = (candidate.website or "").rstrip("/")

    if website:
        if is_external_url(website, source_domain):
            domain = get_domain(website)
            if domain:
                return f"domain:{domain}"
        return f"url:{website}"

    return normalize_company_key(candidate.company_name, candidate.website)


def _website_score(candidate: CompanyCandidate, source_domain: str) -> int:
    if not candidate.website:
        return 0
    if is_external_url(candidate.website, source_domain):
        return 2
    return 1


def _candidate_sort_key(candidate: CompanyCandidate) -> tuple:
    source_domain = get_domain(candidate.source_url) or ""
    category_len = len(candidate.source_category or "")
    notes_len = len(candidate.notes or "")
    return (
        _website_score(candidate, source_domain),
        candidate.confidence,
        category_len,
        notes_len,
    )


def _is_better(new: CompanyCandidate, existing: CompanyCandidate) -> bool:
    return _candidate_sort_key(new) > _candidate_sort_key(existing)


def _find_name_match(
    candidate: CompanyCandidate,
    grouped: dict[str, CompanyCandidate],
) -> str | None:
    for key, existing in grouped.items():
        if key.startswith("domain:") or key.startswith("url:"):
            continue
        score = fuzz.token_sort_ratio(
            candidate.company_name.lower(),
            existing.company_name.lower(),
        )
        if score >= NAME_SIMILARITY_THRESHOLD:
            return key
    return None


def deduplicate_candidates(candidates: list[CompanyCandidate]) -> list[CompanyCandidate]:
    """Deduplicate candidates across sources, keeping the best record for each company."""
    grouped: dict[str, CompanyCandidate] = {}

    for candidate in candidates:
        key = _dedupe_key(candidate)
        existing = grouped.get(key)
        if existing is None:
            name_match_key = _find_name_match(candidate, grouped)
            if name_match_key is not None:
                existing = grouped[name_match_key]
                if _is_better(candidate, existing):
                    del grouped[name_match_key]
                    grouped[key] = candidate
                continue
            grouped[key] = candidate
            continue

        if _is_better(candidate, existing):
            grouped[key] = candidate

    deduped = list(grouped.values())
    deduped.sort(key=lambda item: (-item.confidence, item.company_name.lower()))
    return deduped
