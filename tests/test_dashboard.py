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
            # Set store_id in session
            with self.client.session_transaction() as sess:
                sess['store_id'] = self.store_id

            # Post to login
            response = self.client.post('/login', data=dict(
                username='testuser',
                password='password'
            ), follow_redirects=True)

            # Check if login successful (or at least redirected to dashboard)
            # The response text checks might depend on the template content
            # But checking 200 OK on dashboard is key

            response = self.client.get('/dashboard')
            self.assertEqual(response.status_code, 200)
            # Check for some content expected on dashboard
            # Note: The dashboard might be empty, but should render
            # 'Appointments Today' is likely present as a label or variable usage
            self.assertIn(b'Appointments Today', response.data)

if __name__ == '__main__':
    unittest.main()
