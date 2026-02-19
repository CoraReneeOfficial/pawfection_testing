import logging
from extensions import db
from sqlalchemy import text, inspect
from sqlalchemy.exc import ProgrammingError, OperationalError

def check_and_fix(app):
    """
    Checks for missing columns in the 'notification' table and adds them if needed.
    """
    logger = logging.getLogger('app.migration')

    with app.app_context():
        try:
            inspector = inspect(db.engine)
            # Check if table exists
            if not inspector.has_table('notification'):
                logger.info("Notification table does not exist. db.create_all() should handle it.")
                return

            columns = [col['name'] for col in inspector.get_columns('notification')]

            # Determine DB type for specific syntax if needed, but standard SQL usually works for ADD COLUMN
            # Postgres: TIMESTAMP, SQLite: DATETIME (affinity)

            with db.engine.connect() as conn:
                trans = conn.begin()
                try:
                    if 'remind_at' not in columns:
                        logger.info("Adding 'remind_at' column to 'notification' table...")
                        # Use TIMESTAMP for Postgres compatibility, SQLite accepts it too
                        conn.execute(text("ALTER TABLE notification ADD COLUMN remind_at TIMESTAMP"))

                    if 'shown_in_popup' not in columns:
                        logger.info("Adding 'shown_in_popup' column to 'notification' table...")
                        conn.execute(text("ALTER TABLE notification ADD COLUMN shown_in_popup BOOLEAN DEFAULT FALSE"))

                    trans.commit()
                    logger.info("Notification schema check/fix complete.")
                except Exception as e:
                    trans.rollback()
                    logger.error(f"Error during manual migration: {e}")
                    # Don't raise, just log. If it fails, the app might crash later, but maybe db.create_all handled it?

        except Exception as e:
            logger.error(f"Failed to inspect or migrate notification table: {e}")
