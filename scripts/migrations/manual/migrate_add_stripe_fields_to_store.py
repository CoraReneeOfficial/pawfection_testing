"""
Migration script to add stripe_customer_id and stripe_subscription_id columns to the store table.
"""
import sqlite3

def main():
    DB_PATH = 'grooming_business_v2.db'
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Add stripe_customer_id
    cur.execute("""
        ALTER TABLE store ADD COLUMN stripe_customer_id VARCHAR(255)
    """)
    # Add stripe_subscription_id
    cur.execute("""
        ALTER TABLE store ADD COLUMN stripe_subscription_id VARCHAR(255)
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Migration complete: stripe_customer_id and stripe_subscription_id added to store table.")

if __name__ == '__main__':
    main()
