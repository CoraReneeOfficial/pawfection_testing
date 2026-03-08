import sqlite3
import os

def migrate_sqlite(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE user ADD COLUMN commission_type VARCHAR(20) DEFAULT 'percentage'")
        cursor.execute("ALTER TABLE user ADD COLUMN commission_amount FLOAT DEFAULT 100.0")
        cursor.execute("ALTER TABLE user ADD COLUMN commission_recipient_id INTEGER")
        conn.commit()
        print("SQLite advanced commission columns added successfully.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("SQLite advanced commission columns already exist.")
        else:
            print(f"Error migrating SQLite: {e}")
    finally:
        conn.close()

def migrate_postgres(db_url=None):
    import psycopg2
    from psycopg2 import sql

    if not db_url:
        db_url = os.environ.get('DATABASE_URL')
        if db_url and db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)

    if not db_url:
        print("[SKIP] No DATABASE_URL provided for Postgres migration.")
        return

    print("Migrating Postgres database (advanced commission)...")
    pg_conn = None
    try:
        pg_conn = psycopg2.connect(db_url)
        pg_conn.autocommit = True
        cur = pg_conn.cursor()

        # Check if table exists
        cur.execute("SELECT to_regclass('public.user');")
        if not cur.fetchone()[0]:
            cur.execute("SELECT to_regclass('public.\"user\"');")
            if not cur.fetchone()[0]:
                print("[SKIP] user table does not exist in Postgres.")
                return

        # Check for commission_type column
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='user' AND column_name='commission_type';
        """)
        if not cur.fetchone():
            print("Adding commission_type, commission_amount, commission_recipient_id columns...")
            try:
                cur.execute('ALTER TABLE "user" ADD COLUMN commission_type VARCHAR(20) DEFAULT \'percentage\';')
                cur.execute('ALTER TABLE "user" ADD COLUMN commission_amount FLOAT DEFAULT 100.0;')
                cur.execute('ALTER TABLE "user" ADD COLUMN commission_recipient_id INTEGER;')
                print("[OK] Added advanced commission columns.")
            except Exception as e:
                print(f"[ERROR] Failed to add advanced commission columns: {e}")
        else:
            print("[SKIP] commission_type column already exists.")

    except Exception as e:
        print(f"[ERROR] Postgres migration failed: {e}")
    finally:
        if pg_conn:
            pg_conn.close()
        print("[DONE] Postgres migration completed.")

if __name__ == "__main__":
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        migrate_postgres()
    else:
        migrate_sqlite('instance/pawfection.db')
