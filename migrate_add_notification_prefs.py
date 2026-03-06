import sqlite3
import os

def migrate_sqlite(db_path):
    if not os.path.exists(db_path):
        return

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Check if columns exist
    c.execute("PRAGMA table_info(owner)")
    columns = [col[1] for col in c.fetchall()]

    try:
        if 'notify_appointment_reminders' not in columns:
            c.execute("ALTER TABLE owner ADD COLUMN notify_appointment_reminders BOOLEAN DEFAULT 1 NOT NULL")
        if 'notify_status_updates' not in columns:
            c.execute("ALTER TABLE owner ADD COLUMN notify_status_updates BOOLEAN DEFAULT 1 NOT NULL")
        if 'notify_marketing' not in columns:
            c.execute("ALTER TABLE owner ADD COLUMN notify_marketing BOOLEAN DEFAULT 1 NOT NULL")
        conn.commit()
    except Exception as e:
        print(f"Error migrating SQLite owner table: {e}")
    finally:
        conn.close()

def migrate_postgres(db_url):
    import psycopg2
    from psycopg2 import sql

    conn = None
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='owner'")
        columns = [row[0] for row in cur.fetchall()]

        if 'notify_appointment_reminders' not in columns:
            cur.execute("ALTER TABLE owner ADD COLUMN notify_appointment_reminders BOOLEAN DEFAULT true NOT NULL")
        if 'notify_status_updates' not in columns:
            cur.execute("ALTER TABLE owner ADD COLUMN notify_status_updates BOOLEAN DEFAULT true NOT NULL")
        if 'notify_marketing' not in columns:
            cur.execute("ALTER TABLE owner ADD COLUMN notify_marketing BOOLEAN DEFAULT true NOT NULL")

    except Exception as e:
        print(f"Error migrating Postgres owner table: {e}")
    finally:
        if conn is not None:
            conn.close()
