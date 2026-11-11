"""OpenRouter fit-scoring client and recent-job selection."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from src.llm.job_triage import triage_jobs
from src.llm.llm_client import LLMClientError, OpenRouterClient, parse_json_object
from src.llm.schemas import JobFitResult
from src.llm.score_jobs import load_jobs_to_score, persist_job_fit, score_jobs
from tests.test_job_triage import _sample_job


class _Response:
    def __init__(self, payload: dict, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text
        self.reason = "error"

    def json(self) -> dict:
        return self._payload


def _scoring_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE companies (company_id INTEGER PRIMARY KEY, company_name TEXT)")
    connection.execute(
        """
        CREATE TABLE job_postings (
            job_id INTEGER PRIMARY KEY,
            company_id INTEGER,
            title TEXT,
            location TEXT,
            description TEXT,
            active INTEGER,
            fit_score REAL,
            fit_reason TEXT,
            fit_details TEXT,
            evaluated_at TEXT,
            date_found TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE job_evaluation_queue (
            queue_id INTEGER PRIMARY KEY,
            job_id INTEGER,
            status TEXT,
            completed_at TEXT,
            lease_owner TEXT,
            lease_expires_at TEXT,
            last_error TEXT,
            updated_at TEXT
        )
        """
    )
    connection.execute("INSERT INTO companies (company_id, company_name) VALUES (1, 'Acme')")
    return connection


def _insert_job(connection: sqlite3.Connection, job_id: int, *, description: str, age: str, score: float | None) -> None:
    connection.execute(
        """
        INSERT INTO job_postings (
            job_id, company_id, title, location, description, active, fit_score, date_found
        ) VALUES (?, 1, ?, 'Montreal', ?, 1, ?, datetime('now', ?))
        """,
        (job_id, f"Role {job_id}", description, score, age),
    )


def test_job_fit_result_treats_null_lists_as_empty() -> None:
    result = JobFitResult.model_validate(
        {
            "job_title": "Scientist",
            "company_name": "Acme",
            "fit_score": 6,
            "preferred_qualifications": None,
            "concerns": None,
            "why_fit": None,
            "confidence": None,
        }
    )
    assert result.preferred_qualifications == []
    assert result.concerns == []
    assert result.why_fit == ""
    assert result.confidence == 0.0
    parsed = parse_json_object('```json\n{"fit_score": 7}\n```')
    assert parsed == {"fit_score": 7}


def test_openrouter_client_posts_chat_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    response = _Response({"choices": [{"message": {"content": '{"fit_score": 8}'}}]})
    with patch("src.llm.llm_client.requests.post", return_value=response) as post:
        result = OpenRouterClient(
            {
                "provider": "openrouter",
                "openrouter": {"model": "google/gemma-4-31b-it:free", "api_key_env": "OPENROUTER_API_KEY"},
            }
        ).generate_json("score this")

    assert result == {"fit_score": 8}
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "google/gemma-4-31b-it:free"
    assert payload["messages"][0]["content"] == "score this"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_openrouter_client_requires_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LLMClientError, match="OPENROUTER_API_KEY"):
        OpenRouterClient({"provider": "openrouter", "openrouter": {"api_key_env": "OPENROUTER_API_KEY"}})


def test_load_jobs_to_score_keeps_recent_full_descriptions() -> None:
    connection = _scoring_db()
    _insert_job(connection, 1, description="x" * 250, age="-1 days", score=None)
    _insert_job(connection, 2, description="short stub", age="-1 days", score=None)
    _insert_job(connection, 3, description="y" * 250, age="-10 days", score=None)
    _insert_job(connection, 4, description="z" * 250, age="-1 days", score=7.0)

    recent = load_jobs_to_score(connection, since_days=2, min_description_chars=200, include_scored=False)
    assert [row["job_id"] for row in recent] == [1]

    including_scored = load_jobs_to_score(
        connection, since_days=2, min_description_chars=200, include_scored=True
    )
    assert {row["job_id"] for row in including_scored} == {1, 4}


def test_persist_job_fit_writes_score_and_completes_queue() -> None:
    connection = _scoring_db()
    _insert_job(connection, 1, description="x" * 250, age="-1 days", score=None)
    connection.execute("INSERT INTO job_evaluation_queue (job_id, status) VALUES (1, 'queued')")
    result = JobFitResult(
        job_id=1,
        job_title="Role 1",
        company_name="Acme",
        fit_score=8.5,
        why_fit="Strong overlap.",
        confidence=7,
    )

    persist_job_fit(connection, 1, result)
    stored = connection.execute("SELECT fit_score, fit_reason FROM job_postings WHERE job_id = 1").fetchone()
    queue = connection.execute("SELECT status FROM job_evaluation_queue WHERE job_id = 1").fetchone()
    assert stored["fit_score"] == 8.5
    assert stored["fit_reason"] == "Strong overlap."
    assert queue["status"] == "completed"


def test_hosted_scoring_refuses_an_unbounded_run() -> None:
    summary = score_jobs()
    assert summary.jobs_scored == 0
    assert summary.errors == 1
    assert "since-days" in summary.error_messages[0]


def test_triage_skips_hosted_provider() -> None:
    jobs = [_sample_job()]
    with patch("src.llm.job_triage.load_llm_config", return_value={"provider": "openrouter"}):
        triaged, count = triage_jobs(jobs, enabled=True)
    assert triaged == jobs
    assert count == 1
