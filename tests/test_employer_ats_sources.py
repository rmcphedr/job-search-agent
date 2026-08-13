from __future__ import annotations

import sqlite3

from src.database.migrate import apply_migrations
from src.jobs.employer_ats_sources import (
    backfill_legacy_ats_job_sources,
    identify_ats_source,
    list_ats_sources,
    upsert_ats_source,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.executescript(
        """
        CREATE TABLE companies (
            company_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            website TEXT NOT NULL UNIQUE
        );
        CREATE TABLE job_postings (
            job_id INTEGER PRIMARY KEY,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            source_board TEXT
        );
        CREATE TABLE runs (
            run_id INTEGER PRIMARY KEY,
            run_type TEXT NOT NULL,
            started_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            companies_checked INTEGER,
            notes TEXT
        );
        """
    )
    return connection


def test_identify_canonical_employer_ats_sources() -> None:
    assert identify_ats_source(
        "https://job-boards.greenhouse.io/valencelabs/jobs/123"
    ) == (
        "greenhouse",
        "https://job-boards.greenhouse.io/valencelabs",
        "valencelabs",
    )
    assert identify_ats_source("https://jobs.lever.co/acme/abc") == (
        "lever",
        "https://jobs.lever.co/acme",
        "acme",
    )
    assert identify_ats_source("https://jobs.ashbyhq.com/acme/abc") == (
        "ashby",
        "https://jobs.ashbyhq.com/acme",
        "acme",
    )
    assert identify_ats_source(
        "https://acme.wd5.myworkdayjobs.com/External/job/Toronto/Role_R1"
    ) == (
        "workday",
        "https://acme.wd5.myworkdayjobs.com/External",
        "acme/External",
    )


def test_identify_embedded_ats_source() -> None:
    html = '<a href="https://jobs.lever.co/acme">Open roles</a>'
    assert identify_ats_source("https://acme.example/careers", html) == (
        "lever",
        "https://jobs.lever.co/acme",
        "acme",
    )


def test_migration_registry_upsert_and_list() -> None:
    connection = _connection()
    connection.execute(
        "INSERT INTO companies (company_id, company_name, website) VALUES (1, 'Acme', 'https://acme.test');"
    )
    apply_migrations(connection)
    source_id = upsert_ats_source(
        connection,
        company_id=1,
        provider="greenhouse",
        board_url="https://job-boards.greenhouse.io/acme",
        board_token="acme",
        discovery_method="career_page",
    )
    connection.commit()

    sources = list_ats_sources(connection)
    assert source_id > 0
    assert len(sources) == 1
    assert sources[0].company_name == "Acme"
    assert sources[0].provider == "greenhouse"
    assert sources[0].status == "not_run"


def test_backfill_only_blank_unambiguous_ats_sources() -> None:
    connection = _connection()
    connection.execute(
        "INSERT INTO companies (company_id, company_name, website) VALUES (1, 'Acme', 'https://acme.test');"
    )
    connection.executemany(
        "INSERT INTO job_postings (company_id, title, url, source_board) VALUES (1, ?, ?, ?);",
        [
            ("GH", "https://job-boards.greenhouse.io/acme/jobs/1", None),
            ("Lever", "https://jobs.lever.co/acme/2", "linkedin"),
            ("Other", "https://acme.test/jobs/3", None),
        ],
    )

    assert backfill_legacy_ats_job_sources(connection) == 1
    rows = connection.execute(
        "SELECT title, source_board FROM job_postings ORDER BY job_id"
    ).fetchall()
    assert [(row["title"], row["source_board"]) for row in rows] == [
        ("GH", "greenhouse"),
        ("Lever", "linkedin"),
        ("Other", None),
    ]
