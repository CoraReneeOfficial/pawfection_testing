import sqlite3
import logging
from sqlalchemy import create_engine, text

def migrate_sqlite(db_path):
    """
    Adds Phase 3 fields to the SQLite database if they don't exist.
    """
    logging.info("Checking Phase 3 schema updates (SQLite)...")
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # --- Update Store Table ---
        cursor.execute("PRAGMA table_info(store)")
        store_columns = [col[1] for col in cursor.fetchall()]

        if 'daily_capacity' not in store_columns:
            logging.info("Adding 'daily_capacity' column to 'store' table...")
            cursor.execute("ALTER TABLE store ADD COLUMN daily_capacity INTEGER DEFAULT 20")

        if 'salon_style' not in store_columns:
            logging.info("Adding 'salon_style' column to 'store' table...")
            cursor.execute("ALTER TABLE store ADD COLUMN salon_style VARCHAR(50) DEFAULT 'appointment'")

        # --- Update User Table ---
        cursor.execute("PRAGMA table_info(user)")
        user_columns = [col[1] for col in cursor.fetchall()]

        if 'commission_percentage' not in user_columns:
            logging.info("Adding 'commission_percentage' column to 'user' table...")
            cursor.execute("ALTER TABLE user ADD COLUMN commission_percentage FLOAT DEFAULT 100.0")

        conn.commit()
        logging.info("Phase 3 schema updates complete (SQLite).")
    except Exception as e:
        logging.error(f"Error during Phase 3 migration (SQLite): {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def migrate_postgres(db_url):
    """
    Adds Phase 3 fields to the Postgres database if they don't exist.
    """
    logging.info("Checking Phase 3 schema updates (Postgres)...")
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            # --- Update Store Table ---
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='store' AND column_name='daily_capacity';
            """))
            if not result.fetchone():
                logging.info("Adding 'daily_capacity' column to 'store' table...")
                conn.execute(text("ALTER TABLE store ADD COLUMN daily_capacity INTEGER DEFAULT 20;"))
                conn.commit()

            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='store' AND column_name='salon_style';
            """))
            if not result.fetchone():
                logging.info("Adding 'salon_style' column to 'store' table...")
                conn.execute(text("ALTER TABLE store ADD COLUMN salon_style VARCHAR(50) DEFAULT 'appointment';"))
                conn.commit()

            # --- Update User Table ---
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='user' AND column_name='commission_percentage';
            """))
            if not result.fetchone():
                logging.info("Adding 'commission_percentage' column to 'user' table...")
                conn.execute(text("ALTER TABLE \"user\" ADD COLUMN commission_percentage FLOAT DEFAULT 100.0;"))
                conn.commit()

        logging.info("Phase 3 schema updates complete (Postgres).")
    except Exception as e:
        logging.error(f"Error during Phase 3 migration (Postgres): {e}")

if __name__ == "__main__":
    import os
    # Determine which database is configured
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        migrate_postgres(database_url)
    else:
        # Fallback to local SQLite DB path typically used by app
        db_path = os.path.join(os.path.dirname(__file__), 'grooming_business_v2.db')
        migrate_sqlite(db_path)
