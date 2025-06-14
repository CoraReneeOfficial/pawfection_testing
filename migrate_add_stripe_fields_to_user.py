from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

DATABASE_URL = "sqlite:///C:/Users/coras/Documents/GitHub/pawfection_testing/grooming_business_v2.db"

engine = create_engine(DATABASE_URL)
connection = engine.connect()

ALTERS = [
    "ALTER TABLE user ADD COLUMN stripe_customer_id VARCHAR(255)",
    "ALTER TABLE user ADD COLUMN stripe_subscription_id VARCHAR(255)",
    "ALTER TABLE user ADD COLUMN is_subscribed BOOLEAN NOT NULL DEFAULT 0"
]

for alter in ALTERS:
    try:
        connection.execute(text(alter))
        print(f"Executed: {alter}")
    except ProgrammingError as e:
        print(f"Skipped (maybe already exists): {alter}\nReason: {e}")
    except Exception as e:
        print(f"Error executing: {alter}\nReason: {e}")

connection.close()
print("Migration complete.")