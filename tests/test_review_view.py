"""Focused tests for Quick Review display normalization."""

import math

from src.ui.review_view import (
    _clean_text,
    _detail_items,
    _has_structured_assessment,
    _qualification_assessments,
)


def test_clean_text_hides_missing_value_sentinels() -> None:
    assert _clean_text(None) == ""
    assert _clean_text(float("nan")) == ""
    assert _clean_text("NaN") == ""
    assert _clean_text("null") == ""


def test_detail_items_omits_missing_values() -> None:
    assert _detail_items(["Python", None, math.nan, "N/A", " PyTorch "]) == [
        "Python",
        "PyTorch",
    ]


def test_structured_qualification_is_not_duplicated_by_legacy_lists() -> None:
    details = {
        "qualification_assessment": [
            {"requirement": "Python", "status": "match", "evidence": "Confirmed", "preferred": False}
        ],
        "skills_match": ["Python"],
        "skill_gaps": ["Cloud"],
    }

    assert _qualification_assessments(details, None) == details["qualification_assessment"]


def test_only_nonempty_structured_assessments_are_review_ready() -> None:
    assert _has_structured_assessment('{"qualification_assessment": [{"status": "match"}]}')
    assert not _has_structured_assessment('{"skills_match": ["Python"]}')
    assert not _has_structured_assessment(None)
