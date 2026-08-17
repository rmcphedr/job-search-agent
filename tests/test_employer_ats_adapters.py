from __future__ import annotations

from typing import Any

from src.jobs import employer_ats_adapters as ats


class FakeResponse:
    def __init__(self, payload: Any):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


def test_greenhouse_adapter_extracts_api_jobs(monkeypatch):
    monkeypatch.setattr(
        ats.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {
                "jobs": [
                    {
                        "title": "Machine Learning Scientist",
                        "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123",
                        "location": {"name": "Toronto, ON"},
                        "content": "<p>Build clinical ML systems.</p>",
                        "updated_at": "2026-08-01T12:00:00Z",
                    }
                ]
            }
        ),
    )

    jobs = ats.GreenhouseAdapter().extract("https://boards.greenhouse.io/acme", "")

    assert len(jobs) == 1
    assert jobs[0].title == "Machine Learning Scientist"
    assert jobs[0].location == "Toronto, ON"
    assert jobs[0].description == "Build clinical ML systems."


def test_lever_adapter_extracts_api_jobs(monkeypatch):
    monkeypatch.setattr(
        ats.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            [
                {
                    "text": "Senior Data Scientist",
                    "hostedUrl": "https://jobs.lever.co/acme/abc-123",
                    "categories": {"location": "Remote - Canada"},
                    "descriptionPlain": "Develop production models.",
                }
            ]
        ),
    )

    jobs = ats.LeverAdapter().extract("https://jobs.lever.co/acme", "")

    assert jobs[0].title == "Senior Data Scientist"
    assert jobs[0].url == "https://jobs.lever.co/acme/abc-123"


def test_ashby_adapter_omits_unlisted_jobs(monkeypatch):
    monkeypatch.setattr(
        ats.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {
                "jobs": [
                    {
                        "title": "AI Researcher",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/abc",
                        "location": "Montreal, QC",
                        "descriptionHtml": "<div>Research multimodal models.</div>",
                        "isListed": True,
                    },
                    {"title": "Hidden role", "isListed": False},
                ]
            }
        ),
    )

    jobs = ats.AshbyAdapter().extract("https://jobs.ashbyhq.com/acme", "")

    assert [job.title for job in jobs] == ["AI Researcher"]


def test_workday_adapter_paginates_and_builds_canonical_urls(monkeypatch):
    payloads = [
        {
            "total": 2,
            "jobPostings": [
                {
                    "title": "Data Scientist",
                    "externalPath": "/job/Toronto/Data-Scientist_R123",
                    "locationsText": "Toronto, ON",
                    "postedOn": "Posted Today",
                    "bulletFields": ["Full time"],
                }
            ],
        },
        {
            "total": 2,
            "jobPostings": [
                {
                    "title": "ML Engineer",
                    "externalPath": "/job/Remote/ML-Engineer_R124",
                    "locationsText": "Remote - Canada",
                }
            ],
        },
    ]
    calls: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        return FakeResponse(payloads.pop(0))

    monkeypatch.setattr(ats.requests, "post", fake_post)
    jobs = ats.WorkdayAdapter().extract(
        "https://acme.wd5.myworkdayjobs.com/en-US/External_Careers", ""
    )

    assert [job.title for job in jobs] == ["Data Scientist", "ML Engineer"]
    assert jobs[0].url == (
        "https://acme.wd5.myworkdayjobs.com/External_Careers/job/Toronto/"
        "Data-Scientist_R123"
    )
    assert [call["offset"] for call in calls] == [0, 1]


def test_adapter_failure_returns_empty_list_for_html_fallback(monkeypatch):
    def fail(*args, **kwargs):
        raise ats.requests.RequestException("network unavailable")

    monkeypatch.setattr(ats.requests, "get", fail)
    assert ats.extract_ats_jobs("lever", "https://jobs.lever.co/acme", "") == []
