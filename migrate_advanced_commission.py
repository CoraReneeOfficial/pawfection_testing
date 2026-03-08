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

if __name__ == "__main__":
    migrate_sqlite('instance/pawfection.db')
