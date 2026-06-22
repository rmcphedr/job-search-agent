"""Inspect database table counts and sample company rows."""

from __future__ import annotations

import sqlite3

from src.database.db import get_connection, get_database_path, get_table_counts


def main() -> None:
    db_path = get_database_path()

    try:
        counts = get_table_counts(db_path=db_path)
    except RuntimeError as exc:
        raise SystemExit(f"Inspection failed: {exc}") from exc

    print(f"Database: {db_path}")
    print("Table counts:")
    for table_name, count in counts.items():
        print(f"  {table_name}: {count}")

    try:
        with get_connection(db_path=db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    company_id,
                    company_name,
                    website,
                    industry,
                    location,
                    size,
                    hiring_status,
                    priority,
                    last_checked
                FROM companies
                ORDER BY company_id
                LIMIT 10;
                """
            ).fetchall()
    except sqlite3.Error as exc:
        raise SystemExit(f"Failed to read companies table: {exc}") from exc

    print("\nFirst 10 companies:")
    if not rows:
        print("  (no rows)")
        return

    for row in rows:
        print(
            "  "
            f"id={row['company_id']} | "
            f"name={row['company_name']} | "
            f"website={row['website']} | "
            f"industry={row['industry']} | "
            f"location={row['location']} | "
            f"priority={row['priority']}"
        )


if __name__ == "__main__":
    main()
