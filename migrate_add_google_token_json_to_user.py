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
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user';")
        if not cur.fetchone():
            print("[SKIP] user table does not exist in SQLite DB.")
            return

        # Get existing columns
        cur.execute("PRAGMA table_info(user);")
        columns = [info[1] for info in cur.fetchall()]

        # Add google_token_json column
        if 'google_token_json' not in columns:
            print("Adding google_token_json column...")
            try:
                cur.execute("ALTER TABLE user ADD COLUMN google_token_json TEXT;")
                print("[OK] Added google_token_json column.")
            except Exception as e:
                print(f"[ERROR] Failed to add google_token_json column: {e}")
        else:
            print("[SKIP] google_token_json column already exists.")

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
        cur.execute("SELECT to_regclass('public.user');")
        if not cur.fetchone()[0]:
            # the table is named "user" but sometimes created as "user" with quotes, lets check
            cur.execute("SELECT to_regclass('public.\"user\"');")
            if not cur.fetchone()[0]:
                print("[SKIP] user table does not exist in Postgres.")
                return

        # Check for google_token_json column
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='user' AND column_name='google_token_json';
        """)
        if not cur.fetchone():
            print("Adding google_token_json column...")
            try:
                cur.execute('ALTER TABLE "user" ADD COLUMN google_token_json TEXT;')
                print("[OK] Added google_token_json column.")
            except Exception as e:
                print(f"[ERROR] Failed to add google_token_json column: {e}")
        else:
            print("[SKIP] google_token_json column already exists.")

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
        base_dir = os.path.abspath(os.path.dirname(__file__))
        persistent_data_root = os.environ.get('PERSISTENT_DATA_DIR', '/persistent_storage' if os.path.exists('/persistent_storage') else base_dir)
        db_path = os.path.join(persistent_data_root, 'grooming_business_v2.db')
        migrate_sqlite(db_path)
