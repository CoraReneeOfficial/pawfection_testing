import unittest
import os
import json
import datetime
import sys
from unittest.mock import MagicMock

# Mock dotenv BEFORE importing app to prevent loading .env
sys.modules['dotenv'] = MagicMock()
# Ensure DATABASE_URL is not set to production URL
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

# Mock bcrypt before importing app
mock_bcrypt = MagicMock()
mock_bcrypt.gensalt.return_value = b'$2b$12$salt'
mock_bcrypt.hashpw.return_value = b'$2b$12$hashedpassword'
mock_bcrypt.checkpw.return_value = True
sys.modules['bcrypt'] = mock_bcrypt
sys.modules['bcrypt._bcrypt'] = MagicMock()

# Mock authlib to avoid cryptography dependency issues
sys.modules['authlib'] = MagicMock()
sys.modules['authlib.integrations'] = MagicMock()
sys.modules['authlib.integrations.flask_client'] = MagicMock()
sys.modules['authlib.jose'] = MagicMock()

from datetime import timezone
from app import create_app, db
from models import User, Store, Owner, Dog, Appointment, Receipt

class ReceiptPaginationTestCase(unittest.TestCase):
    def setUp(self):
        # Use in-memory DB for testing
        os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            # Create store
            self.store = Store(name="TestStore", username="teststore", email="test@test.com", subscription_status='active')
            self.store.set_password("password")
            db.session.add(self.store)
            db.session.commit()

            # Create user
            self.user = User(username="testuser", store_id=self.store.id, role="groomer")
            self.user.set_password("password")
            db.session.add(self.user)
            db.session.commit()

            # Create owner
            self.owner = Owner(name="Test Owner", phone_number="1234567890", email="owner@test.com", store_id=self.store.id)
            db.session.add(self.owner)
            db.session.commit()

            # Create dog
            self.dog = Dog(name="Test Dog", owner_id=self.owner.id, store_id=self.store.id)
            db.session.add(self.dog)
            db.session.commit()

            # Create 25 receipts
            self.create_receipts(25)

    def create_receipts(self, count):
        with self.app.app_context():
            # Use query.get for older sqlalchemy versions if needed, or session.get
            user = db.session.query(User).get(self.user.id)
            store = db.session.query(Store).get(self.store.id)
            dog = db.session.query(Dog).get(self.dog.id)

            for i in range(count):
                # Create appointment
                appt = Appointment(
                    dog_id=dog.id,
                    store_id=store.id,
                    created_by_user_id=user.id,
                    appointment_datetime=datetime.datetime.now(timezone.utc),
                    status='Completed',
                    checkout_total_amount=100.0 + i # Vary the amount
                )
                db.session.add(appt)
                db.session.flush()

                # Create receipt
                receipt_json = json.dumps({
                    'customer_name': self.owner.name,
                    'pet_name': self.dog.name,
                    'final_total': 100.0 + i,
                    'date': datetime.datetime.now().strftime('%Y-%m-%d')
                })

                receipt = Receipt(
                    appointment_id=appt.id,
                    store_id=store.id,
                    owner_id=self.owner.id,
                    receipt_json=receipt_json,
                    created_at=datetime.datetime.now(timezone.utc) - datetime.timedelta(minutes=i) # Vary time slightly
                )
                db.session.add(receipt)

            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self):
        with self.client.session_transaction() as sess:
            sess['store_id'] = self.store.id
            sess['user_id'] = self.user.id
            sess['_user_id'] = str(self.user.id) # Flask-Login needs this

    def test_receipt_pagination(self):
        self.login()
        response = self.client.get('/receipts')
        self.assertEqual(response.status_code, 200)

        # Check that we only see 20 receipts (default page size)
        content = response.data.decode('utf-8')
        # Each receipt has a "View" button with title="View"
        view_count = content.count('title="View"')
        self.assertEqual(view_count, 20, f"Expected 20 receipts, found {view_count}")

        # Check for pagination controls
        self.assertIn('class="pagination"', content)
        # Should have page 2 link
        self.assertIn('page=2', content)

    def test_receipt_filtering(self):
        self.login()
        # Filter by min_total=124 (should match 124.0 and above)
        # We created 0 to 24, adding 100 -> 100.0 to 124.0
        # So min_total=124 should return 1 result (124.0)

        response = self.client.get('/receipts?min_total=124')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')

        view_count = content.count('title="View"')
        self.assertEqual(view_count, 1, f"Expected 1 receipt, found {view_count}")
        self.assertIn('124.00', content)

    def test_receipt_with_missing_fields_no_crash(self):
        self.login()
        with self.app.app_context():
            # Create a receipt with missing fields
            user = db.session.query(User).get(self.user.id)
            store = db.session.query(Store).get(self.store.id)
            dog = db.session.query(Dog).get(self.dog.id)

            appt = Appointment(
                dog_id=dog.id,
                store_id=store.id,
                created_by_user_id=user.id,
                appointment_datetime=datetime.datetime.now(timezone.utc),
                status='Completed',
                checkout_total_amount=99.99
            )
            db.session.add(appt)
            db.session.flush()

            # Empty JSON or missing 'final_total'
            receipt = Receipt(
                appointment_id=appt.id,
                store_id=store.id,
                owner_id=self.owner.id,
                receipt_json="{}",
                created_at=datetime.datetime.now(timezone.utc)
            )
            db.session.add(receipt)
            db.session.commit()

        response = self.client.get('/receipts')
        self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main()
