import unittest
import os
import sys
from unittest.mock import MagicMock

# Mock dotenv BEFORE importing app to prevent loading .env
sys.modules['dotenv'] = MagicMock()


# Ensure DATABASE_URL is not set to production URL
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app, db
from models import User, Store

class DashboardTestCase(unittest.TestCase):
    def setUp(self):
        # Use in-memory DB for testing
        os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            # Create store and user with active subscription
            store = Store(name="TestStore", username="teststore", email="test@test.com", subscription_status='active')
            store.set_password("password")
            db.session.add(store)
            db.session.commit()

            user = User(username="testuser", store_id=store.id, role="groomer")
            user.set_password("password")
            db.session.add(user)
            db.session.commit()

            self.user_id = user.id
            self.store_id = store.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_dashboard_loads(self):
        with self.client:
            # Set store_id and user_id directly in session to bypass login complexities if needed,
            # or use the login route properly.
            with self.client.session_transaction() as sess:
                sess['store_id'] = self.store_id
                sess['user_id'] = self.user_id # Force login for tests

            response = self.client.get('/dashboard')
            self.assertEqual(response.status_code, 200)

            # Since the user is a groomer, we check for groomer specific content
            # such as 'My Stats (Today)'
            self.assertIn(b'My Stats', response.data)

if __name__ == '__main__':
    unittest.main()
