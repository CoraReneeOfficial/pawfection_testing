import os
from flask import Flask
from models import db
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def column_exists(engine, table_name, column_name):
    insp = db.inspect(engine)
    columns = [col['name'] for col in insp.get_columns(table_name)]
    return column_name in columns

def run_manual_migration():
    """Diagnose and add gallery_images column to Store table if it doesn't exist."""
    try:
        app = Flask(__name__)
        db_path = os.path.join(os.path.dirname(__file__), "grooming_business_v2.db")
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

        db.init_app(app)

        with app.app_context():
            engine = db.engine
            insp = db.inspect(engine)
            try:
                tables = insp.get_table_names()
                logger.info(f"Tables found in the database: {tables}")
                print(f"Tables found in the database: {tables}")
            except Exception as e:
                logger.error(f"Error inspecting tables: {e}")
                print(f"Error inspecting tables: {e}")
                return False
            # Now try the normal logic
            if 'store' not in tables:
                logger.error("Table 'store' does not exist. Please check your database and model.")
                print("Table 'store' does not exist. Please check your database and model.")
                return False
            if column_exists(engine, 'store', 'gallery_images'):
                logger.info("'gallery_images' column already exists in 'store' table. No action taken.")
                print("'gallery_images' column already exists in 'store' table. No action taken.")
            else:
                logger.info("Adding 'gallery_images' column to 'store' table...")
                print("Adding 'gallery_images' column to 'store' table...")
                with engine.connect() as conn:
                    conn.execute('ALTER TABLE store ADD COLUMN gallery_images TEXT')
                logger.info("Successfully added 'gallery_images' column to 'store' table.")
                print("Successfully added 'gallery_images' column to 'store' table.")
        return True
    except Exception as e:
        logger.error(f"Migration failed with error: {str(e)}")
        print(f"Migration failed with error: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("Starting manual migration for gallery_images column...")
    success = run_manual_migration()
    if success:
        logger.info("Migration completed successfully.")
    else:
        logger.error("Migration failed. Check the logs for details.")
