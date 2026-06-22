"""Initialize the SQLite database from schema.sql."""

from __future__ import annotations

from src.database.db import SCHEMA_FILE, get_database_path, get_table_counts, execute_sql_file


def main() -> None:
    db_path = get_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    execute_sql_file(SCHEMA_FILE, db_path=db_path)

    print(f"Database initialized successfully at {db_path}")
    print("Table counts:")
    for table_name, count in get_table_counts(db_path=db_path).items():
        print(f"  {table_name}: {count}")


if __name__ == "__main__":
    main()
