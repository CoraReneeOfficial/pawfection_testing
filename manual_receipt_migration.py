# Manual migration script to create the Receipt table for finalized receipts
# Run this script once with your Flask app context active

from app import create_app
from extensions import db
from sqlalchemy import Column, Integer, ForeignKey, DateTime, Text, String, inspect
import datetime

def run_manual_receipt_migration():
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        if not inspector.has_table('receipt'):
            db.engine.execute('''
                CREATE TABLE receipt (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    appointment_id INTEGER NOT NULL REFERENCES appointment (id),
                    store_id INTEGER NOT NULL REFERENCES store (id),
                    owner_id INTEGER REFERENCES owner (id),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    receipt_json TEXT NOT NULL,
                    filename VARCHAR(255)
                )
            ''')
            print('Receipt table created successfully.')
        else:
            print('Receipt table already exists.')

if __name__ == '__main__':
    run_manual_receipt_migration()
