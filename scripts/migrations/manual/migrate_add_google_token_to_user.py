import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'instance', 'pawfection.db')

def migrate():
    print(f"Connecting to database at {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Check if the column exists in the 'user' table
        cursor.execute("PRAGMA table_info(user)")
        columns = [info[1] for info in cursor.fetchall()]

        if 'google_token_json' not in columns:
            print("Adding google_token_json column to user table...")
            cursor.execute("ALTER TABLE user ADD COLUMN google_token_json TEXT;")
            conn.commit()
            print("Successfully added google_token_json column.")
        else:
            print("Column google_token_json already exists in user table.")

    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
