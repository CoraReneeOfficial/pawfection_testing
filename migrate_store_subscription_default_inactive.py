"""
Migration script to set default for Store.subscription_status to 'inactive' and update all existing stores to 'inactive' if currently 'active'.
Works for SQLite and PostgreSQL.
"""
from extensions import db
from models import Store

def run_migration():
    # 1. Update default value for new stores (already changed in model)
    # 2. Update all existing stores with 'active' to 'inactive' (require subscription)
    updated = 0
    stores = Store.query.filter_by(subscription_status='active').all()
    for store in stores:
        store.subscription_status = 'inactive'
        updated += 1
    db.session.commit()
    print(f"Updated {updated} stores to subscription_status='inactive'.")

if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        run_migration()
