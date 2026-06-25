"""Local LLM fit scoring for companies and jobs."""

from __future__ import annotations

from src.llm.company_fit import score_company, score_company_safe
from src.llm.job_fit import score_job, score_job_safe
from src.llm.job_triage import triage_job, triage_job_safe
from src.llm.llm_client import LLMClientError, OllamaClient, load_llm_config
from src.llm.score_exports import load_company_fit_scores, load_job_fit_scores
from src.llm.schemas import CompanyFitResult, JobFitResult, JobTriageResult

__all__ = [
    "CompanyFitResult",
    "JobFitResult",
    "JobTriageResult",
    "LLMClientError",
    "OllamaClient",
    "load_company_fit_scores",
    "load_job_fit_scores",
    "load_llm_config",
    "score_company",
    "score_company_safe",
    "score_job",
    "score_job_safe",
    "triage_job",
    "triage_job_safe",
]
