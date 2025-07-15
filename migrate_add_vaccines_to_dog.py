#!/usr/bin/env python
from extensions import db
from models import Dog
import sys
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

"""
Migration script to add the vaccines field to the Dog model.
This script will:
1. Add the vaccines column to the Dog table if it doesn't exist
2. Print a confirmation message when complete
"""

def migrate():
    print("Starting migration to add vaccines field to Dog model...")
    
    conn = db.engine.connect()
    try:
        # Add the vaccines column to the dog table
        print("Adding 'vaccines' column to Dog table...")
        conn.execute(text("ALTER TABLE dog ADD COLUMN vaccines TEXT"))
        print("Successfully added 'vaccines' column to Dog table.")
    except ProgrammingError as e:
        if 'duplicate column' in str(e).lower():
            print("'vaccines' column already exists in Dog table. No changes made.")
        else:
            raise
    finally:
        conn.close()
    
    print("Migration completed successfully.")

if __name__ == '__main__':
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            migrate()
    except Exception as e:
        print(f"Error during migration: {e}")
        sys.exit(1)
