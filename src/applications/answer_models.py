"""Validated contract for a staged application answer."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    approval_status: Literal["confirmed", "approval_required", "human_required"]

    @field_validator("field_key", "answer")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip()
