"""Pydantic models for extracted job candidates."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.discovery.link_utils import clean_url


class JobCandidate(BaseModel):
    company_name: str
    company_id: int | None = None
    title: str
    location: str | None = None
    url: str | None = None
    description: str | None = None
    date_posted: str | None = None
    provider: str | None = None
    source_career_page: str
    keyword_score: float = 0.0
    matched_keywords: list[str] = Field(default_factory=list)
    content_hash: str | None = None
    notes: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title must be non-empty.")
        return cleaned

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_url(value) or value.strip()
        return cleaned or None

    @field_validator("keyword_score")
    @classmethod
    def validate_keyword_score(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("keyword_score must be between 0 and 1.")
        return value
