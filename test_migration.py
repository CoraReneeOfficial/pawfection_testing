import os
import psycopg2
from urllib.parse import urlparse

db_url = os.environ.get('DATABASE_URL')
print(f"DATABASE_URL: {db_url}")

if db_url:
    parsed = urlparse(db_url)
    try:
        conn = psycopg2.connect(
            dbname=parsed.path[1:],
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port
        )
        print("Connected to PostgreSQL database!")
        cursor = conn.cursor()

        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='appointment' AND column_name='deposit_amount';")
        if not cursor.fetchone():
            print("Column 'deposit_amount' not found. Adding it...")
            cursor.execute("ALTER TABLE appointment ADD COLUMN deposit_amount FLOAT DEFAULT 0.0")
            conn.commit()
            print("Column added successfully!")
        else:
            print("Column 'deposit_amount' already exists.")

        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='appointment';")
        columns = [row[0] for row in cursor.fetchall()]
        print(f"Columns in 'appointment' table: {columns}")

    except Exception as e:
        print(f"Error: {e}")
