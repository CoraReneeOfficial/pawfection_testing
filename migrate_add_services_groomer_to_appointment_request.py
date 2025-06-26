"""Standalone migration script to add requested_services_text and groomer_id columns to the appointment_request table.

Usage:
    python migrate_add_services_groomer_to_appointment_request.py

The script works with both SQLite (default) and Postgres (when DATABASE_URL env var is set).
It is safe to run multiple times – it checks whether columns already exist before attempting
an ALTER TABLE.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import closing

# Optional postgres deps
try:
    import psycopg2  # type: ignore
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT  # type: ignore
except ImportError:  # pragma: no cover
    psycopg2 = None  # type: ignore

# Column DDL fragments
SERVICES_COL = "requested_services_text TEXT"
GROOMER_COL = "groomer_id INTEGER"

def run_sqlite_migration(db_path: str) -> None:
    print(f"[SQLite] Using DB file: {db_path}")
    if not os.path.exists(db_path):
        print("[ERROR] SQLite database file not found.")
        sys.exit(1)

    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")  # Just adding columns

        cur.execute("PRAGMA table_info(appointment_request);")
        existing_cols = {row[1] for row in cur.fetchall()}

        if "requested_services_text" not in existing_cols:
            print("[SQLite] Adding requested_services_text column …")
            cur.execute(f"ALTER TABLE appointment_request ADD COLUMN {SERVICES_COL};")
        else:
            print("[SQLite] requested_services_text already exists – skipping.")

        if "groomer_id" not in existing_cols:
            print("[SQLite] Adding groomer_id column …")
            cur.execute(f"ALTER TABLE appointment_request ADD COLUMN {GROOMER_COL};")
        else:
            print("[SQLite] groomer_id already exists – skipping.")

        conn.commit()
    print("[SQLite] Migration complete ✅")


def run_postgres_migration(pg_url: str) -> None:  # pragma: no cover
    if psycopg2 is None:
        print("[ERROR] psycopg2 is not installed. Install it or run against SQLite.")
        sys.exit(1)

    print(f"[Postgres] Connecting to {pg_url}")
    conn = psycopg2.connect(pg_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    def column_exists(column_name: str) -> bool:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name='appointment_request' AND column_name=%s;
            """,
            (column_name,),
        )
        return cur.fetchone() is not None

    if not column_exists("requested_services_text"):
        print("[Postgres] Adding requested_services_text column …")
        cur.execute(f"ALTER TABLE appointment_request ADD COLUMN {SERVICES_COL};")
    else:
        print("[Postgres] requested_services_text already exists – skipping.")

    if not column_exists("groomer_id"):
        print("[Postgres] Adding groomer_id column …")
        cur.execute(f"ALTER TABLE appointment_request ADD COLUMN {GROOMER_COL};")
    else:
        print("[Postgres] groomer_id already exists – skipping.")

    cur.close()
    conn.close()
    print("[Postgres] Migration complete ✅")


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        run_postgres_migration(database_url)
    else:
        default_sqlite_path = os.environ.get("SQLITE_DB_PATH", os.path.join(os.getcwd(), "app.db"))
        run_sqlite_migration(default_sqlite_path)


if __name__ == "__main__":
    main()
