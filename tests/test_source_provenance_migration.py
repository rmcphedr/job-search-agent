from src.database.db import SCHEMA_FILE, get_connection
from src.database.migrate import apply_migrations


def test_legacy_alert_labels_are_normalized_once(tmp_path) -> None:
    conn = get_connection(tmp_path / "jobs.db")
    conn.executescript(SCHEMA_FILE.read_text())
    conn.execute("INSERT INTO companies(company_id,company_name,website) VALUES(1,'Acme','https://acme.test')")
    conn.execute(
        "INSERT INTO job_postings(company_id,title,source_board) VALUES(1,'Scientist','LinkedIn Gmail alert')"
    )
    conn.commit()
    apply_migrations(conn)
    apply_migrations(conn)
    row = conn.execute("SELECT source_board,source_channel FROM job_postings").fetchone()
    assert tuple(row) == ("linkedin", "gmail_alert")
    conn.close()
