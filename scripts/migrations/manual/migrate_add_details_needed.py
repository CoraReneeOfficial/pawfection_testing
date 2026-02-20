import os
import psycopg2

# Railway provides these environment variables
PGHOST = os.environ.get("PGHOST")
PGUSER = os.environ.get("PGUSER")
PGPASSWORD = os.environ.get("PGPASSWORD")
PGDATABASE = os.environ.get("PGDATABASE")
PGPORT = os.environ.get("PGPORT", 5432)

def main():
    conn = psycopg2.connect(
        host=PGHOST,
        user=PGUSER,
        password=PGPASSWORD,
        dbname=PGDATABASE,
        port=PGPORT
    )
    cur = conn.cursor()

    # List of new columns to add to the store table: (name, SQL type, default, nullable)
    new_columns = [
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
        ("is_archived", "BOOLEAN", "FALSE", False)
    ]

    for col, sqltype, default, nullable in new_columns:
        cur.execute(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='store' AND column_name=%s;
        """, (col,))
        if cur.fetchone():
            print(f"Column '{col}' already exists. Skipping.")
        else:
            alter = f"ALTER TABLE store ADD COLUMN {col} {sqltype}"
            if not nullable:
                alter += " NOT NULL"
            if default is not None:
                alter += f" DEFAULT {default}"
            alter += ";"
            cur.execute(alter)
            print(f"Column '{col}' added successfully.")

    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()