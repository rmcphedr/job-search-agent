"""Pydantic schemas for LLM fit scoring results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _clamp_score(value: float) -> float:
    return max(0.0, min(10.0, float(value)))


class CompanyFitResult(BaseModel):
    company_name: str
    fit_score: float = Field(ge=0, le=10)
    industry_alignment: float = Field(ge=0, le=10)
    mission_alignment: float = Field(ge=0, le=10)
    career_alignment: float = Field(ge=0, le=10)
    growth_potential: float = Field(ge=0, le=10)
    reasoning: str
    best_roles: list[str] = Field(default_factory=list)
    interesting_factors: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=10)

    @field_validator(
        "fit_score",
        "industry_alignment",
        "mission_alignment",
        "career_alignment",
        "growth_potential",
        "confidence",
        mode="before",
    )
    @classmethod
    def validate_scores(cls, value: Any) -> float:
        if value is None or value == "":
            return 0.0
        return _clamp_score(value)


class QualificationAssessment(BaseModel):
    requirement: str
    status: Literal["match", "gap"]
    evidence: str
    preferred: bool = False


class JobFitResult(BaseModel):
    job_id: int | None = None
    job_title: str
    company_name: str
    fit_score: float = Field(ge=0, le=10)
    salary: str | None = None
    seniority: str | None = None
    employment_type: str | None = None
    role_summary: list[str] = Field(default_factory=list)
    job_requirements: list[str] = Field(default_factory=list)
    preferred_qualifications: list[str] = Field(default_factory=list)
    qualification_assessment: list[QualificationAssessment] = Field(default_factory=list)
    skills_match: list[str] = Field(default_factory=list)
    skill_gaps: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    why_fit: str
    concerns: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=10)

    @field_validator("fit_score", "confidence", mode="before")
    @classmethod
    def validate_scores(cls, value: Any) -> float:
        if value is None or value == "":
            return 0.0
        return _clamp_score(value)


class JobTriageResult(BaseModel):
    job_title: str
    company_name: str
    worth_reviewing: bool
    triage_score: float = Field(ge=0, le=10)
    reason: str
    matched_role_signals: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=10)

    @field_validator("triage_score", "confidence", mode="before")
    @classmethod
    def validate_scores(cls, value: Any) -> float:
        if value is None or value == "":
            return 0.0
        return _clamp_score(value)
