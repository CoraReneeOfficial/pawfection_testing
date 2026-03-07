import sqlite3
import os
import sys

def migrate_sqlite(db_path):
    """Adds the composite index for notification to SQLite database if it doesn't exist."""
    print(f"Starting SQLite index migration for db: {db_path}")
    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}. Assuming it will be created with the correct schema.")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if index exists
        cursor.execute("PRAGMA index_list('notification');")
        indexes = cursor.fetchall()
        index_names = [idx[1] for idx in indexes]

        if 'idx_notification_store_is_read' not in index_names:
            print("Adding 'idx_notification_store_is_read' index to notification table...")
            cursor.execute("CREATE INDEX idx_notification_store_is_read ON notification (store_id, is_read);")
            conn.commit()
            print("Index added successfully.")
        else:
            print("Index 'idx_notification_store_is_read' already exists. No action taken.")

    except sqlite3.Error as e:
        print(f"SQLite error during migration: {e}", file=sys.stderr)
    finally:
        if conn:
            conn.close()

def migrate_postgres(db_url):
    """Adds the composite index for notification to Postgres database if it doesn't exist."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    print(f"Starting Postgres index migration.")
    conn = None
    try:
        conn = psycopg2.connect(db_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'notification' AND indexname = 'idx_notification_store_is_read';
        """)

        if not cursor.fetchone():
            print("Adding 'idx_notification_store_is_read' index to notification table...")
            cursor.execute("CREATE INDEX CONCURRENTLY idx_notification_store_is_read ON notification (store_id, is_read);")
            print("Index added successfully.")
        else:
            print("Index 'idx_notification_store_is_read' already exists. No action taken.")

    except psycopg2.Error as e:
         print(f"Postgres error during migration: {e}", file=sys.stderr)
    finally:
        if conn:
            cursor.close()
            conn.close()

if __name__ == '__main__':
    # Simple test execution if run directly
    db_path = 'instance/pawfection.db'
    migrate_sqlite(db_path)
