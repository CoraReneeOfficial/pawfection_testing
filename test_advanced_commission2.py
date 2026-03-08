import sqlite3

def check_db():
    conn = sqlite3.connect('instance/pawfection.db')
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(user)")
    columns = [col[1] for col in cursor.fetchall()]
    print(columns)
    if 'commission_type' in columns and 'commission_amount' in columns and 'commission_recipient_id' in columns:
        print("Commission columns verified.")
    else:
        print("Missing columns.")
    conn.close()

check_db()
