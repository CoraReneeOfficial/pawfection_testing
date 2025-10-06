"""
Migration script to add email fields to User and Store tables
if they don't already exist.
"""

import os
import sqlite3
import sys

# Path to the database
DB_PATH = r"C:\Users\coras\Documents\GitHub\pawfection_testing\grooming_business_v2.db"

def check_column_exists(conn, table_name, column_name):
    """Check if a column exists in a table"""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    for column in columns:
        if column[1] == column_name:
            return True
    return False

def add_column_if_not_exists(conn, table_name, column_name, column_type):
    """Add a column to a table if it doesn't exist"""
    if not check_column_exists(conn, table_name, column_name):
        print(f"Adding {column_name} column to {table_name} table...")
        cursor = conn.cursor()
        try:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            conn.commit()
            print(f"Successfully added {column_name} column to {table_name} table.")
            return True
        except sqlite3.Error as e:
            print(f"Error adding column {column_name} to {table_name}: {e}")
            return False
    else:
        print(f"Column {column_name} already exists in {table_name} table.")
        return False

def main():
    """Main function to run migrations"""
    # Check if DB file exists
    if not os.path.exists(DB_PATH):
        print(f"Database file not found at {DB_PATH}")
        print("Please check the path and try again.")
        sys.exit(1)
    
    print(f"Connecting to database at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    
    # Add email column to Store table if it doesn't exist
    added_store_email = add_column_if_not_exists(conn, 'store', 'email', 'TEXT')
    
    # Add email column to User table if it doesn't exist
    added_user_email = add_column_if_not_exists(conn, 'user', 'email', 'TEXT')
    
    if added_store_email or added_user_email:
        print("Migration completed successfully.")
    else:
        print("No changes were made. Email columns already exist.")
    
    conn.close()

if __name__ == "__main__":
    main()
