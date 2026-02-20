"""Migration script to add remind_at and shown_in_popup columns to notification table.

Usage:
    python migrate_add_remind_at_to_notification.py
"""
import os
import sqlite3
from contextlib import closing

def migrate_sqlite(db_path: str):
    print(f"Migrating SQLite database at {db_path}...")
    if not os.path.exists(db_path):
        print(f"[SKIP] Database file {db_path} does not exist.")
        return

    with closing(sqlite3.connect(db_path)) as conn:
        cur = conn.cursor()

        # Check if table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notification';")
        if not cur.fetchone():
            print("[SKIP] notification table does not exist in SQLite DB.")
            return

        # Get existing columns
        cur.execute("PRAGMA table_info(notification);")
        columns = [info[1] for info in cur.fetchall()]

        # Add remind_at column
        if 'remind_at' not in columns:
            print("Adding remind_at column...")
            try:
                cur.execute("ALTER TABLE notification ADD COLUMN remind_at DATETIME;")
                print("[OK] Added remind_at column.")
            except Exception as e:
                print(f"[ERROR] Failed to add remind_at column: {e}")
        else:
            print("[SKIP] remind_at column already exists.")

        # Add shown_in_popup column
        if 'shown_in_popup' not in columns:
            print("Adding shown_in_popup column...")
            try:
                cur.execute("ALTER TABLE notification ADD COLUMN shown_in_popup BOOLEAN NOT NULL DEFAULT 0;")
                print("[OK] Added shown_in_popup column.")
            except Exception as e:
                print(f"[ERROR] Failed to add shown_in_popup column: {e}")
        else:
            print("[SKIP] shown_in_popup column already exists.")

        conn.commit()
        print("[DONE] SQLite migration completed.")

def migrate_postgres(db_url=None):
    import psycopg2
    from psycopg2 import sql

    if not db_url:
        db_url = os.environ.get('DATABASE_URL')

    if not db_url:
        print("[SKIP] No DATABASE_URL provided for Postgres migration.")
        return

    print("Migrating Postgres database...")
    try:
        pg_conn = psycopg2.connect(db_url)
        pg_conn.autocommit = True
        cur = pg_conn.cursor()

        # Check if table exists
        cur.execute("SELECT to_regclass('public.notification');")
        if not cur.fetchone()[0]:
            print("[SKIP] notification table does not exist in Postgres.")
            return

        # Check for remind_at column
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='notification' AND column_name='remind_at';
        """)
        if not cur.fetchone():
            print("Adding remind_at column...")
            try:
                cur.execute("ALTER TABLE notification ADD COLUMN remind_at TIMESTAMP;")
                print("[OK] Added remind_at column.")
            except Exception as e:
                print(f"[ERROR] Failed to add remind_at column: {e}")
        else:
            print("[SKIP] remind_at column already exists.")

        # Check for shown_in_popup column
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='notification' AND column_name='shown_in_popup';
        """)
        if not cur.fetchone():
            print("Adding shown_in_popup column...")
            try:
                cur.execute("ALTER TABLE notification ADD COLUMN shown_in_popup BOOLEAN NOT NULL DEFAULT FALSE;")
                print("[OK] Added shown_in_popup column.")
            except Exception as e:
                print(f"[ERROR] Failed to add shown_in_popup column: {e}")
        else:
            print("[SKIP] shown_in_popup column already exists.")

        pg_conn.close()
        print("[DONE] Postgres migration completed.")

    except Exception as e:
        print(f"[ERROR] Postgres migration failed: {e}")

if __name__ == '__main__':
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        migrate_postgres()
    else:
        # Default SQLite path used in app.py
        # PERSISTENT_DATA_ROOT defaults to current dir if not set/exists
        base_dir = os.path.abspath(os.path.dirname(__file__))
        persistent_data_root = os.environ.get('PERSISTENT_DATA_DIR', '/persistent_storage' if os.path.exists('/persistent_storage') else base_dir)
        db_path = os.path.join(persistent_data_root, 'grooming_business_v2.db')
        migrate_sqlite(db_path)
