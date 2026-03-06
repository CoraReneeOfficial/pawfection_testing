"""Migration script to add Phase 2 Settings columns to the Store and User tables.

Usage:
    python migrate_phase2_settings.py
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

        # Migrate Store table
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='store';")
        if cur.fetchone():
            cur.execute("PRAGMA table_info(store);")
            columns = [info[1] for info in cur.fetchall()]

            store_cols_to_add = [
                ("capacity_type", "VARCHAR(20) NOT NULL DEFAULT 'appointments'"),
                ("capacity_limit", "INTEGER"),
                ("appointment_window_start", "VARCHAR(10)"),
                ("appointment_window_end", "VARCHAR(10)"),
                ("salon_style", "VARCHAR(20) NOT NULL DEFAULT 'staggered'"),
                ("schedule_type", "VARCHAR(20) NOT NULL DEFAULT 'system'")
            ]

            for col_name, col_def in store_cols_to_add:
                if col_name not in columns:
                    print(f"Adding {col_name} column to store table...")
                    try:
                        cur.execute(f"ALTER TABLE store ADD COLUMN {col_name} {col_def};")
                        print(f"[OK] Added {col_name} column to store table.")
                    except Exception as e:
                        print(f"[ERROR] Failed to add {col_name} column to store table: {e}")
                else:
                    print(f"[SKIP] {col_name} column already exists in store table.")
        else:
            print("[SKIP] store table does not exist in SQLite DB.")

        # Migrate User table
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user';")
        if cur.fetchone():
            cur.execute("PRAGMA table_info(user);")
            columns = [info[1] for info in cur.fetchall()]

            user_cols_to_add = [
                ("employment_type", "VARCHAR(20)"),
                ("address", "VARCHAR(255)"),
                ("deduction_type", "VARCHAR(20)"),
                ("deduction_amount", "FLOAT"),
                ("deduction_frequency", "VARCHAR(20)"),
                ("other_withholdings", "TEXT")
            ]

            for col_name, col_def in user_cols_to_add:
                if col_name not in columns:
                    print(f"Adding {col_name} column to user table...")
                    try:
                        cur.execute(f"ALTER TABLE user ADD COLUMN {col_name} {col_def};")
                        print(f"[OK] Added {col_name} column to user table.")
                    except Exception as e:
                        print(f"[ERROR] Failed to add {col_name} column to user table: {e}")
                else:
                    print(f"[SKIP] {col_name} column already exists in user table.")
        else:
            print("[SKIP] user table does not exist in SQLite DB.")

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

        # Migrate Store table
        cur.execute("SELECT to_regclass('public.store');")
        if cur.fetchone()[0]:
            store_cols_to_add = [
                ("capacity_type", "VARCHAR(20) NOT NULL DEFAULT 'appointments'"),
                ("capacity_limit", "INTEGER"),
                ("appointment_window_start", "VARCHAR(10)"),
                ("appointment_window_end", "VARCHAR(10)"),
                ("salon_style", "VARCHAR(20) NOT NULL DEFAULT 'staggered'"),
                ("schedule_type", "VARCHAR(20) NOT NULL DEFAULT 'system'")
            ]
            for col_name, col_def in store_cols_to_add:
                cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='store' AND column_name='{col_name}';")
                if not cur.fetchone():
                    print(f"Adding {col_name} column to store table...")
                    try:
                        cur.execute(f"ALTER TABLE store ADD COLUMN {col_name} {col_def};")
                        print(f"[OK] Added {col_name} column to store table.")
                    except Exception as e:
                        print(f"[ERROR] Failed to add {col_name} column to store table: {e}")
                else:
                    print(f"[SKIP] {col_name} column already exists in store table.")
        else:
            print("[SKIP] store table does not exist in Postgres.")

        # Migrate User table
        cur.execute("SELECT to_regclass('public.user');")
        if cur.fetchone()[0]:
            user_cols_to_add = [
                ("employment_type", "VARCHAR(20)"),
                ("address", "VARCHAR(255)"),
                ("deduction_type", "VARCHAR(20)"),
                ("deduction_amount", "DOUBLE PRECISION"),
                ("deduction_frequency", "VARCHAR(20)"),
                ("other_withholdings", "TEXT")
            ]
            for col_name, col_def in user_cols_to_add:
                cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='user' AND column_name='{col_name}';")
                if not cur.fetchone():
                    print(f"Adding {col_name} column to user table...")
                    try:
                        cur.execute(f"ALTER TABLE \"user\" ADD COLUMN {col_name} {col_def};")
                        print(f"[OK] Added {col_name} column to user table.")
                    except Exception as e:
                        print(f"[ERROR] Failed to add {col_name} column to user table: {e}")
                else:
                    print(f"[SKIP] {col_name} column already exists in user table.")
        else:
            print("[SKIP] user table does not exist in Postgres.")

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
