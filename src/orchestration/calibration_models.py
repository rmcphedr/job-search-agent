"""Calibration models and persistence for discovery run feedback."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CalibrationCorrection(BaseModel):
    company_name: str
    original_fit_score: float | None = Field(default=None, ge=0, le=10)
    corrected_fit_score: float = Field(ge=0, le=10)
    feedback: str = ""

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("company_name must be non-empty")
        return cleaned


class CalibrationFile(BaseModel):
    corrections: list[CalibrationCorrection] = Field(default_factory=list)
    preference_updates: list[str] = Field(default_factory=list)
    applied_to_evaluations: bool = False
    applied_to_profile: bool = False
    applied_at: str | None = None

    @field_validator("preference_updates", mode="before")
    @classmethod
    def clean_preference_updates(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
