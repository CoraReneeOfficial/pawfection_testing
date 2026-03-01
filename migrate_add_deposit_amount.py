import sqlite3
from urllib.parse import urlparse

def get_db_path():
    """Retrieve database path from environment variable or use default."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    db_url = os.environ.get('DATABASE_URL')
    if db_url and db_url.startswith('sqlite:///'):
        return db_url.replace('sqlite:///', '')
    return "pawfection.db"

def migrate_sqlite(db_path=None):
    if db_path is None:
        db_path = get_db_path()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(appointment)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'deposit_amount' not in columns:
            print(f"Adding deposit_amount column to appointment table in SQLite database {db_path}...")
            cursor.execute("ALTER TABLE appointment ADD COLUMN deposit_amount FLOAT DEFAULT 0.0")
            print("Successfully added deposit_amount column.")
        else:
            print("deposit_amount column already exists in appointment table.")

        conn.commit()
    except Exception as e:
        print(f"Error during SQLite migration: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def migrate_postgres(db_url):
    try:
        import psycopg2
        parsed = urlparse(db_url)
        conn = psycopg2.connect(
            dbname=parsed.path[1:],
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port
        )
        cursor = conn.cursor()

        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='appointment' AND column_name='deposit_amount';
        """)

        if not cursor.fetchone():
            print(f"Adding deposit_amount column to appointment table in PostgreSQL...")
            cursor.execute("ALTER TABLE appointment ADD COLUMN deposit_amount FLOAT DEFAULT 0.0")
            print("Successfully added deposit_amount column.")
        else:
            print("deposit_amount column already exists in appointment table.")

        conn.commit()
    except Exception as e:
        print(f"Error during PostgreSQL migration: {e}")
    finally:
        if 'conn' in locals() and conn:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    db_url = os.environ.get('DATABASE_URL')

    if db_url and db_url.startswith('postgresql'):
        migrate_postgres(db_url)
    else:
        migrate_sqlite()
