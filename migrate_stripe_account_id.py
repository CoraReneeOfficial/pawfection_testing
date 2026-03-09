import os
import sqlite3

def migrate_sqlite():
    db_path = os.environ.get('SQLITE_DB_PATH', 'instance/pawfection.db')
    print(f"Migrating SQLite database at {db_path}...")

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if the column already exists
        cursor.execute("PRAGMA table_info(store)")
        columns = [info[1] for info in cursor.fetchall()]

        if 'stripe_account_id' not in columns:
            print("Adding 'stripe_account_id' to 'store' table...")
            cursor.execute("ALTER TABLE store ADD COLUMN stripe_account_id VARCHAR(255)")
            conn.commit()
            print("Successfully added 'stripe_account_id' to SQLite database.")
        else:
            print("'stripe_account_id' already exists in SQLite database.")

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    finally:
        if conn:
            conn.close()

def migrate_postgres(db_url=None):
    try:
        import psycopg2
        from psycopg2 import sql
    except ImportError:
        print("psycopg2 not installed. Skipping PostgreSQL migration.")
        return

    if db_url is None:
        db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("DATABASE_URL environment variable not set. Skipping PostgreSQL migration.")
        return

    # Handle Heroku's postgres:// prefix
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    print(f"Migrating PostgreSQL database...")

    conn = None
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cursor = conn.cursor()

        # Check if column exists
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='store' AND column_name='stripe_account_id';
        """)

        if not cursor.fetchone():
            print("Adding 'stripe_account_id' to 'store' table...")
            cursor.execute("ALTER TABLE store ADD COLUMN stripe_account_id VARCHAR(255);")
            print("Successfully added 'stripe_account_id' to PostgreSQL database.")
        else:
            print("'stripe_account_id' already exists in PostgreSQL database.")

    except psycopg2.Error as e:
        print(f"PostgreSQL error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        migrate_postgres()
    else:
        migrate_sqlite()
