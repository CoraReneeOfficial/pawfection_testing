import sqlite3

# Path to your SQLite database file
import os
DB_PATH = os.path.abspath('grooming_business_v2.db')  # Always use absolute path

# List of (column name, SQL type, default, nullable)
columns = [
    ("logo_filename", "VARCHAR(200)", None, True),
    ("status", "VARCHAR(20)", "'active'", False),
    ("business_hours", "TEXT", None, True),
    ("description", "TEXT", None, True),
    ("facebook_url", "VARCHAR(255)", None, True),
    ("instagram_url", "VARCHAR(255)", None, True),
    ("website_url", "VARCHAR(255)", None, True),
    ("tax_id", "VARCHAR(100)", None, True),
    ("notification_preferences", "TEXT", None, True),
    ("default_appointment_duration", "INTEGER", None, True),
    ("default_appointment_buffer", "INTEGER", None, True),
    ("payment_settings", "TEXT", None, True),
    ("is_archived", "BOOLEAN", "0", False)
]

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for col, sqltype, default, nullable in columns:
        if column_exists(cur, 'store', col):
            print(f"Column '{col}' already exists. Skipping.")
            continue
        alter = f"ALTER TABLE store ADD COLUMN {col} {sqltype}"
        if not nullable:
            alter += " NOT NULL"
        if default is not None:
            alter += f" DEFAULT {default}"
        alter += ";"
        cur.execute(alter)
        print(f"Column '{col}' added.")
    conn.commit()
    cur.close()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    main()
