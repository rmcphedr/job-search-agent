from pathlib import Path

from src.database.db import get_connection
from src.integrations.obsidian_jobs import parse_obsidian_clipping, sync_obsidian_clippings


def _write_clip(root: Path, body: str = "Full detailed posting") -> Path:
    clipping = root / "Clippings" / "role.md"
    clipping.parent.mkdir(parents=True)
    clipping.write_text(
        '---\ntitle: "Staff/Senior Staff/Principal Scientist (Neuroscience) | Cortical Labs"\n'
        'source: "https://linkedin.com/jobs/view/123?tracking=x"\ncreated: 2026-08-10\n---\n'
        + body, encoding="utf-8")
    return clipping


def test_parse_obsidian_clipping(tmp_path: Path) -> None:
    parsed = parse_obsidian_clipping(_write_clip(tmp_path))
    assert parsed.company_name == "Cortical Labs"
    assert parsed.url == "https://linkedin.com/jobs/view/123?tracking=x"
    assert parsed.description == "Full detailed posting"


def test_parse_infers_company_from_obsidian_description(tmp_path: Path) -> None:
    clipping = tmp_path / "Clippings" / "maxwell.md"
    clipping.parent.mkdir(parents=True)
    clipping.write_text(
        '---\ntitle: "Electrophysiology Data Analysis Engineer"\n'
        'source: "https://mxwbio.com/jobs/engineer"\n'
        'description: "Join MaxWell Biosystems as Computational Neuroscientist in Zurich."\n'
        '---\nAt MaxWell Biosystems, we innovate the future of electrophysiology.',
        encoding="utf-8",
    )
    parsed = parse_obsidian_clipping(clipping)
    assert parsed.company_name == "MaxWell Biosystems"
    assert parsed.title == "Electrophysiology Data Analysis Engineer"


def test_sync_updates_placeholder_and_invalidates_evaluation(tmp_path, monkeypatch) -> None:
    _write_clip(tmp_path)
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr("src.integrations.obsidian_jobs.get_connection", lambda: get_connection(db_path))
    connection = get_connection(db_path)
    connection.executescript("""
      CREATE TABLE companies (company_id INTEGER PRIMARY KEY, company_name TEXT, website TEXT);
      CREATE TABLE job_postings (
        job_id INTEGER PRIMARY KEY, company_id INTEGER, title TEXT, location TEXT, url TEXT,
        description TEXT, date_found TEXT, active INTEGER, fit_score REAL, fit_reason TEXT,
        source_board TEXT, discovery_run_id TEXT, keyword_score REAL, matched_keywords TEXT,
        evaluated_at TEXT, description_status TEXT, description_source TEXT,
        description_source_url TEXT, description_checked_at TEXT, description_error TEXT,
        fit_details TEXT);
      INSERT INTO companies VALUES (1, 'Cortical Labs', 'https://corticallabs.com');
      INSERT INTO job_postings (job_id, company_id, title, url, description, active, fit_score, fit_reason)
      VALUES (581, 1, 'Staff / Senior Staff / Principal Scientist (Neuroscience)',
              'https://lnkd.in/old', 'Short placeholder', 1, 9.0, 'old score');
    """)
    connection.commit()
    connection.close()
    result = sync_obsidian_clippings(pipeline_root=tmp_path)
    assert result.updated == 1
    check = get_connection(db_path)
    row = check.execute("SELECT * FROM job_postings WHERE job_id = 581").fetchone()
    check.close()
    assert row["description"] == "Full detailed posting"
    assert row["description_status"] == "enriched"
    assert row["description_source"] == "obsidian_clip"
    assert row["fit_score"] is None


def test_sync_creates_missing_company_and_job(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr("src.integrations.obsidian_jobs.get_connection", lambda: get_connection(db_path))
    connection = get_connection(db_path)
    connection.executescript("""
      CREATE TABLE companies (
        company_id INTEGER PRIMARY KEY, company_name TEXT, website TEXT, industry TEXT,
        location TEXT, size TEXT, hiring_status TEXT, priority TEXT, last_checked TEXT,
        created_at TEXT, updated_at TEXT);
      CREATE TABLE job_postings (
        job_id INTEGER PRIMARY KEY, company_id INTEGER, title TEXT, location TEXT, url TEXT,
        description TEXT, date_found TEXT DEFAULT CURRENT_TIMESTAMP, active INTEGER,
        fit_score REAL, fit_reason TEXT, source_board TEXT, discovery_run_id TEXT,
        keyword_score REAL, matched_keywords TEXT, evaluated_at TEXT,
        description_status TEXT, description_source TEXT, description_source_url TEXT,
        description_checked_at TEXT, description_error TEXT, fit_details TEXT);
    """)
    connection.commit()
    connection.close()
    _write_clip(tmp_path)
    result = sync_obsidian_clippings(pipeline_root=tmp_path)
    assert result.companies_created == 1
    assert result.inserted == 1
    check = get_connection(db_path)
    row = check.execute("""SELECT c.company_name, j.description_status
                           FROM job_postings j JOIN companies c USING (company_id)""").fetchone()
    check.close()
    assert tuple(row) == ("Cortical Labs", "enriched")
