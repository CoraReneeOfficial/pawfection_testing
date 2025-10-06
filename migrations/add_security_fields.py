import sqlite3
import os
import sys

def run_migration():
    """
    Add security_question and security_answer_hash columns to User and Store tables
    """
    try:
        # Use the specific database path provided
        db_path = r"C:\Users\coras\Documents\GitHub\pawfection_testing\grooming_business_v2.db"
        
        print(f"Using database at path: {db_path}")
        
        # Connect to the SQLite database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if the columns already exist in User table
        cursor.execute("PRAGMA table_info(user)")
        user_columns = [col[1] for col in cursor.fetchall()]
        
        if 'security_question' not in user_columns:
            print("Adding security_question column to user table")
            cursor.execute("ALTER TABLE user ADD COLUMN security_question TEXT")
        else:
            print("Column security_question already exists in user table")
            
        if 'security_answer_hash' not in user_columns:
            print("Adding security_answer_hash column to user table")
            cursor.execute("ALTER TABLE user ADD COLUMN security_answer_hash TEXT")
        else:
            print("Column security_answer_hash already exists in user table")
            
        # Check if the columns already exist in Store table
        cursor.execute("PRAGMA table_info(store)")
        store_columns = [col[1] for col in cursor.fetchall()]
        
        if 'security_question' not in store_columns:
            print("Adding security_question column to store table")
            cursor.execute("ALTER TABLE store ADD COLUMN security_question TEXT")
        else:
            print("Column security_question already exists in store table")
            
        if 'security_answer_hash' not in store_columns:
            print("Adding security_answer_hash column to store table")
            cursor.execute("ALTER TABLE store ADD COLUMN security_answer_hash TEXT")
        else:
            print("Column security_answer_hash already exists in store table")
        
        # Commit the changes
        conn.commit()
        conn.close()
        
        print("Migration completed successfully")
        return True
    except Exception as e:
        print(f"Error during migration: {str(e)}")
        return False

if __name__ == "__main__":
    run_migration()
