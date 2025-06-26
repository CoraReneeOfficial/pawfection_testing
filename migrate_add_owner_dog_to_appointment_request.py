"""Standalone migration script to add owner_id and dog_id columns to the appointment_request table.

Usage:
    python migrate_add_owner_dog_to_appointment_request.py

The script works with both SQLite (default) and Postgres (when DATABASE_URL env var is set).
It is safe to run multiple times – it checks whether columns already exist before attempting
an ALTER TABLE.
"""
import os
import sqlite3
import sys
from contextlib import closing

# Optional postgres deps
try:
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
except ImportError:
    psycopg2 = None  # type: ignore

OWNER_COLUMN = "owner_id INTEGER"
DOG_COLUMN = "dog_id INTEGER"


def run_sqlite_migration(db_path: str):
    print(f"[SQLite] Using DB file: {db_path}")
    if not os.path.exists(db_path):
        print("[ERROR] SQLite database file not found.")
        sys.exit(1)

    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")  # Safe-guard – we are only adding columns

        cur.execute("PRAGMA table_info(appointment_request);")
        existing_cols = {row[1] for row in cur.fetchall()}

        if "owner_id" not in existing_cols:
            print("[SQLite] Adding owner_id column …")
            cur.execute(f"ALTER TABLE appointment_request ADD COLUMN {OWNER_COLUMN};")
        else:
            print("[SQLite] owner_id already exists – skipping.")

        if "dog_id" not in existing_cols:
            print("[SQLite] Adding dog_id column …")
            cur.execute(f"ALTER TABLE appointment_request ADD COLUMN {DOG_COLUMN};")
        else:
            print("[SQLite] dog_id already exists – skipping.")

        conn.commit()
    print("[SQLite] Migration complete ✅")


def run_postgres_migration(pg_url: str):
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

    if not column_exists("owner_id"):
        print("[Postgres] Adding owner_id column …")
        cur.execute(f"ALTER TABLE appointment_request ADD COLUMN {OWNER_COLUMN};")
    else:
        print("[Postgres] owner_id already exists – skipping.")

    if not column_exists("dog_id"):
        print("[Postgres] Adding dog_id column …")
        cur.execute(f"ALTER TABLE appointment_request ADD COLUMN {DOG_COLUMN};")
    else:
        print("[Postgres] dog_id already exists – skipping.")

    cur.close()
    conn.close()
    print("[Postgres] Migration complete ✅")


def main():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        run_postgres_migration(database_url)
    else:
        # Default SQLite path logic copied from app.py (if exists) or fallback to ./app.db
        default_sqlite_path = os.environ.get("SQLITE_DB_PATH", os.path.join(os.getcwd(), "app.db"))
        run_sqlite_migration(default_sqlite_path)


if __name__ == "__main__":
    main()
