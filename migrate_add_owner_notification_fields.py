"""Migration script to add phone_carrier, text_notifications_enabled, and email_notifications_enabled columns to owner table.

Usage:
    python migrate_add_owner_notification_fields.py
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
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='owner';")
        if not cur.fetchone():
            print("[SKIP] owner table does not exist in SQLite DB.")
            return

        # Get existing columns
        cur.execute("PRAGMA table_info(owner);")
        columns = [info[1] for info in cur.fetchall()]

        # Add phone_carrier column
        if 'phone_carrier' not in columns:
            print("Adding phone_carrier column...")
            try:
                cur.execute("ALTER TABLE owner ADD COLUMN phone_carrier VARCHAR(50);")
                print("[OK] Added phone_carrier column.")
            except Exception as e:
                print(f"[ERROR] Failed to add phone_carrier column: {e}")
        else:
            print("[SKIP] phone_carrier column already exists.")

        # Add text_notifications_enabled column
        if 'text_notifications_enabled' not in columns:
            print("Adding text_notifications_enabled column...")
            try:
                cur.execute("ALTER TABLE owner ADD COLUMN text_notifications_enabled BOOLEAN NOT NULL DEFAULT 1;")
                print("[OK] Added text_notifications_enabled column.")
            except Exception as e:
                print(f"[ERROR] Failed to add text_notifications_enabled column: {e}")
        else:
            print("[SKIP] text_notifications_enabled column already exists.")

        # Add email_notifications_enabled column
        if 'email_notifications_enabled' not in columns:
            print("Adding email_notifications_enabled column...")
            try:
                cur.execute("ALTER TABLE owner ADD COLUMN email_notifications_enabled BOOLEAN NOT NULL DEFAULT 1;")
                print("[OK] Added email_notifications_enabled column.")
            except Exception as e:
                print(f"[ERROR] Failed to add email_notifications_enabled column: {e}")
        else:
            print("[SKIP] email_notifications_enabled column already exists.")

        conn.commit()
        print("[DONE] SQLite migration completed.")

def migrate_postgres(db_url=None):
    try:
        import psycopg2
    except ImportError:
        print("[SKIP] psycopg2 not installed, skipping Postgres migration.")
        return

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
        cur.execute("SELECT to_regclass('public.owner');")
        if not cur.fetchone()[0]:
            print("[SKIP] owner table does not exist in Postgres.")
            return

        # Check for phone_carrier column
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='owner' AND column_name='phone_carrier';
        """)
        if not cur.fetchone():
            print("Adding phone_carrier column...")
            try:
                cur.execute("ALTER TABLE owner ADD COLUMN phone_carrier VARCHAR(50);")
                print("[OK] Added phone_carrier column.")
            except Exception as e:
                print(f"[ERROR] Failed to add phone_carrier column: {e}")
        else:
            print("[SKIP] phone_carrier column already exists.")

        # Check for text_notifications_enabled column
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='owner' AND column_name='text_notifications_enabled';
        """)
        if not cur.fetchone():
            print("Adding text_notifications_enabled column...")
            try:
                cur.execute("ALTER TABLE owner ADD COLUMN text_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE;")
                print("[OK] Added text_notifications_enabled column.")
            except Exception as e:
                print(f"[ERROR] Failed to add text_notifications_enabled column: {e}")
        else:
            print("[SKIP] text_notifications_enabled column already exists.")

        # Check for email_notifications_enabled column
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='owner' AND column_name='email_notifications_enabled';
        """)
        if not cur.fetchone():
            print("Adding email_notifications_enabled column...")
            try:
                cur.execute("ALTER TABLE owner ADD COLUMN email_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE;")
                print("[OK] Added email_notifications_enabled column.")
            except Exception as e:
                print(f"[ERROR] Failed to add email_notifications_enabled column: {e}")
        else:
            print("[SKIP] email_notifications_enabled column already exists.")

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
