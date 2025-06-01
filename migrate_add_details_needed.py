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

    # Check if the column already exists
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name='appointment' AND column_name='details_needed';
    """)
    if cur.fetchone():
        print("Column 'details_needed' already exists. No changes made.")
    else:
        cur.execute("""
            ALTER TABLE appointment
            ADD COLUMN details_needed BOOLEAN NOT NULL DEFAULT FALSE;
        """)
        print("Column 'details_needed' added successfully.")

    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()