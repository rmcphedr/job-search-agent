"""Configuration and conservative token estimates for agent evaluations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class EvaluationPolicy(BaseModel):
    default_model: str = "gpt-5.6-terra"
    normal_reasoning_effort: str = "low"
    escalation_reasoning_effort: str = "medium"
    confidence_threshold: float = Field(default=6.0, ge=0, le=10)
    batch_size: int = Field(default=5, ge=1)
    lease_seconds: int = Field(default=900, ge=30)
    max_attempts: int = Field(default=2, ge=1)
    max_jobs_per_run: int = Field(default=10, ge=1)
    estimated_token_limit: int = Field(default=50_000, ge=1)
    model_rates: dict[str, dict[str, float]] = {}


@dataclass(frozen=True)
class UsageEstimate:
    tokens: int
    provenance: str = "estimated"


def estimate_tokens(text: str) -> UsageEstimate:
    return UsageEstimate(tokens=math.ceil(len(text) / 4))


def load_evaluation_policy(path: Path | None = None) -> EvaluationPolicy:
    config_path = path or Path("config/agent_evaluation.yaml")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return EvaluationPolicy.model_validate(raw)
