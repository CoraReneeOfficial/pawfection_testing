import unittest
from unittest.mock import MagicMock, patch
import os
import tempfile
import sys

# Add venv/Lib/site-packages to sys.path to load dependencies
# Keep this for local dev compatibility
sys.path.append(os.path.join(os.getcwd(), 'venv', 'Lib', 'site-packages'))
# Add project root to path
sys.path.append('.')

from flask import url_for, session

# Mock dotenv to prevent loading .env file which might contain DATABASE_URL
sys.modules['dotenv'] = MagicMock()

# Conditionally mock dependencies as in test_ci_health.py
try:
    import bcrypt
except ImportError:
    sys.modules['bcrypt'] = MagicMock()
    sys.modules['bcrypt'].hashpw.return_value = b'hashed_password'
    sys.modules['bcrypt'].gensalt.return_value = b'salt'
    sys.modules['bcrypt'].checkpw.return_value = True

try:
    import cryptography
except ImportError:
    sys.modules['cryptography'] = MagicMock()
    sys.modules['cryptography.x509'] = MagicMock()
    sys.modules['cryptography.hazmat'] = MagicMock()
    sys.modules['cryptography.hazmat.backends'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.serialization'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.asymmetric'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.asymmetric.rsa'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.asymmetric.ec'] = MagicMock()
    sys.modules['authlib'] = MagicMock()
    sys.modules['authlib.integrations'] = MagicMock()
    sys.modules['authlib.integrations.flask_client'] = MagicMock()

try:
    import google.oauth2
except ImportError:
    sys.modules['google.oauth2'] = MagicMock()
    sys.modules['google.oauth2.credentials'] = MagicMock()
    sys.modules['googleapiclient'] = MagicMock()
    sys.modules['googleapiclient.discovery'] = MagicMock()
    sys.modules['googleapiclient.errors'] = MagicMock()
    sys.modules['google_auth_oauthlib'] = MagicMock()
    sys.modules['google_auth_oauthlib.flow'] = MagicMock()
    sys.modules['google.auth'] = MagicMock()
    sys.modules['google.auth.transport'] = MagicMock()

try:
    import psycopg2
except ImportError:
    sys.modules['psycopg2'] = MagicMock()
    class MockError(Exception): pass
    sys.modules['psycopg2'].Error = MockError

try:
    import fpdf
except ImportError:
    sys.modules['fpdf'] = MagicMock()

try:
    import xlsxwriter
except ImportError:
    sys.modules['xlsxwriter'] = MagicMock()

try:
    import psutil
except ImportError:
    sys.modules['psutil'] = MagicMock()

# Unset DATABASE_URL to avoid connecting to production DB during import
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

from app import create_app, db
from models import User, Store

class TestUIEmptyState(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create a Store
        self.store = Store(name="Test Store", username="teststore", email="store@test.com")
        self.store.set_password("password")
        self.store.subscription_status = 'active'
        db.session.add(self.store)
        db.session.commit()

        # Create a User (Admin)
        self.user = User(username="testuser", email="user@test.com", store_id=self.store.id, role="admin")
        self.user.set_password("password")
        db.session.add(self.user)
        db.session.commit()

        # Mock login session
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['store_id'] = self.store.id
            sess['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_appointments_needs_review_empty_state(self):
        """Test that the needs review page shows a nice empty state when no appointments exist."""
        # 1. Ensure no appointments exist (default state)
        # 2. Request the page
        response = self.client.get('/appointments/needs_review')
        self.assertEqual(response.status_code, 200)

        html = response.data.decode('utf-8')

        # Check for the empty state elements we WANT to see
        # We expect this test to FAIL initially (Red phase)
        # because these elements are not yet in the template

        # We check for the specific 'All caught up!' text which is part of our UX improvement
        self.assertIn('All caught up!', html, "Should see 'All caught up!' message")

        # We check for the empty-state class
        self.assertIn('empty-state', html, "Should use the .empty-state CSS class")

        # We check for a dashboard link
        self.assertIn('href="/dashboard"', html, "Should have a link back to dashboard")

if __name__ == '__main__':
    unittest.main()
