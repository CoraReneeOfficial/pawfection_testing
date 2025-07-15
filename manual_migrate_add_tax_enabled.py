"""
Manual migration script to add 'tax_enabled' boolean column to the store table.
Run this script with your Flask app context.
"""
from extensions import db
from sqlalchemy import Boolean, Column
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

def add_tax_enabled_column():
    conn = db.engine.connect()
    try:
        conn.execute(text("ALTER TABLE store ADD COLUMN tax_enabled BOOLEAN NOT NULL DEFAULT TRUE"))
        print("Added 'tax_enabled' column to 'store' table.")
    except ProgrammingError as e:
        if 'duplicate column' in str(e).lower():
            print("Column 'tax_enabled' already exists. Skipping.")
        else:
            raise
    finally:
        conn.close()

if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        add_tax_enabled_column()
        print('Migration complete.')
