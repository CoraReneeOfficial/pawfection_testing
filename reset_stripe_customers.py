"""
Reset all Stripe customer and subscription IDs for all stores in the database.
Use this when switching between Stripe test/live environments or after changing API keys.
"""
from app import create_app
from models import Store, db

app = create_app()
with app.app_context():
    stores = Store.query.all()
    for store in stores:
        store.stripe_customer_id = None
        store.stripe_subscription_id = None
    db.session.commit()
print("Reset all store Stripe customer and subscription IDs.")
