"""Simple one-off migration script to add the appointment_request table.

Usage (from repo root):
    python migrate_add_appointment_request.py

The script works for the default SQLite DB (grooming_business_v2.db).
If you are pointing the app at Postgres via the DATABASE_URL env-var, first
export the same variable in your shell and the script will use psycopg2 to run
an equivalent CREATE TABLE (if not exists) statement.
"""
import os
import sqlite3
from contextlib import closing

# Column DDL fragment shared by both engines
TABLE_DDL = (
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "store_id INTEGER NOT NULL,"
    "customer_name VARCHAR(100) NOT NULL,"
    "phone VARCHAR(20) NOT NULL,"
    "email VARCHAR(120),"
    "dog_name VARCHAR(100),"
    "preferred_datetime VARCHAR(100),"
    "notes TEXT,"
    "status VARCHAR(20) NOT NULL DEFAULT 'pending',"
    "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
)

def migrate_sqlite(db_path: str):
    with closing(sqlite3.connect(db_path)) as conn:
        cur = conn.cursor()
        # Check if table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='appointment_request';")
        if cur.fetchone():
            print("[SKIP] appointment_request table already exists in SQLite DB.")
            return
        cur.execute(f"CREATE TABLE appointment_request ({TABLE_DDL});")
        # Basic FK index on store_id for faster joins
        cur.execute("CREATE INDEX idx_appt_req_store_id ON appointment_request(store_id);")
        conn.commit()
        print("[OK] appointment_request table created in SQLite DB.")

def migrate_postgres():
    import psycopg2
    from psycopg2 import sql

    pg_conn = psycopg2.connect(os.environ['DATABASE_URL'])
    pg_conn.autocommit = True
    cur = pg_conn.cursor()
    # Check for existence
    cur.execute("""
        SELECT to_regclass('public.appointment_request');
    """)
    if cur.fetchone()[0]:
        print("[SKIP] appointment_request table already exists in Postgres.")
        return
    ddl = sql.SQL(
        "CREATE TABLE appointment_request (" + TABLE_DDL + ","
        "FOREIGN KEY (store_id) REFERENCES store(id) ON DELETE CASCADE)"
    )
    cur.execute(ddl)
    print("[OK] appointment_request table created in Postgres.")

if __name__ == '__main__':
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        migrate_postgres()
    else:
        # Default SQLite path used in app.py
        db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'grooming_business_v2.db')
        migrate_sqlite(db_path)
