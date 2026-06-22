"""Pydantic models for directory source discovery."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class DirectorySource(BaseModel):
    source_id: str
    name: str
    url: str
    strategy: str
    source_domain: str
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    include_categories: list[str] = Field(default_factory=list)
    exclude_categories: list[str] = Field(default_factory=list)
    soft_include_tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class CompanyCandidate(BaseModel):
    company_name: str
    website: str | None = None
    source_id: str
    source_name: str
    source_url: str
    source_category: str | None = None
    confidence: float = 0.5
    notes: str | None = None

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("company_name must be non-empty after stripping whitespace.")
        return cleaned

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1.")
        return value
