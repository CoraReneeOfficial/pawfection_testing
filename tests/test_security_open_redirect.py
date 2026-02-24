
import os
import sys
import uuid
from unittest.mock import MagicMock

# 1. Mock dotenv to avoid loading .env file content
sys.modules['dotenv'] = MagicMock()

# 2. Unset DATABASE_URL to force app.py to use SQLite
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

# 3. Import app AFTER mocking
try:
    from app import create_app, db
    from models import User, Store
except Exception as e:
    print(f"Error importing app: {e}")
    sys.exit(1)

import unittest

class TestOpenRedirect(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['WTF_CSRF_METHODS'] = []
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

        self.client = self.app.test_client()

        with self.app.app_context():
            # Ensure clean slate
            db.drop_all()
            db.create_all()

            uid = uuid.uuid4().hex[:8]
            self.store_username = f"teststore_{uid}"
            self.user_username = f"testuser_{uid}"

            store = Store(name=f"Test Store {uid}", username=self.store_username, email=f"store_{uid}@test.com")
            store.set_password("password")
            db.session.add(store)
            db.session.commit()

            self.store_id = store.id

            user = User(username=self.user_username, role="admin", store_id=store.id, email=f"user_{uid}@test.com")
            user.set_password("password")
            db.session.add(user)
            db.session.commit()

            self.user_id = user.id

    def test_open_redirect(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['store_id'] = self.store_id

        # Use the stored username
        response = self.client.post('/login?next=//google.com', data={
            'username': self.user_username,
            'password': 'password'
        }, follow_redirects=False)

        if response.status_code != 302:
            print(f"Response status: {response.status_code}")
            print(f"Response data: {response.data.decode('utf-8')}")

        self.assertEqual(response.status_code, 302)
        print(f"Redirect location: {response.location}")

        # VERIFICATION: Should NOT start with //
        self.assertFalse(response.location.startswith('//'), f"Still redirecting to malicious URL: {response.location}")

        # Should redirect to dashboard (fallback)
        # Note: Flask test client location might be absolute (http://localhost/dashboard) or relative depending on config
        self.assertIn('/dashboard', response.location)
        self.assertNotIn('google.com', response.location)

if __name__ == '__main__':
    unittest.main()
