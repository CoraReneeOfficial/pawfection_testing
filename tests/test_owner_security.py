import unittest
from unittest.mock import MagicMock
import sys
import os
import re

# Mock dotenv before importing app
sys.modules['dotenv'] = MagicMock()
sys.modules['dotenv'].load_dotenv = MagicMock()

# Mock bcrypt before importing app
mock_bcrypt = MagicMock()
mock_bcrypt.gensalt.return_value = b'$2b$12$somesalt'
mock_bcrypt.hashpw.return_value = b'$2b$12$hashedpassword'
mock_bcrypt.checkpw.return_value = True
sys.modules['bcrypt'] = mock_bcrypt

# Mock other modules
sys.modules['psutil'] = MagicMock()
sys.modules['stripe'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()

# Prevent database connection attempt in app.py if it tries to load from env
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

from app import create_app, db
from models import User, Store, Owner

class TestOwnerCSRF(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = True  # Enable CSRF
        self.app.config['WTF_CSRF_CHECK_DEFAULT'] = False
        # Set secret key for CSRF
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create a store with active subscription
            store = Store(name="Test Store", username="teststore", email="test@example.com", subscription_status='active')
            store.set_password("password")
            db.session.add(store)
            db.session.commit()
            self.store_id = store.id

            # Create an admin user
            user = User(username='admin', role='admin', is_admin=True, store_id=self.store_id, email="admin@example.com")
            user.set_password('password')
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['store_id'] = self.store_id
            sess['_fresh'] = True

    def test_add_owner_csrf_protected(self):
        """Test that adding an owner WITHOUT a CSRF token FAILS (400 Bad Request)"""
        self.login()

        # Try to add owner WITHOUT CSRF token
        response = self.client.post('/add_owner', data={
            'name': 'Malicious Owner',
            'phone': '123-456-7890'
        }, follow_redirects=True)

        # Should FAIL (400 Bad Request) because CSRF protection is active
        self.assertEqual(response.status_code, 400)

        # Verify owner was NOT created
        with self.app.app_context():
            owner = Owner.query.filter_by(name='Malicious Owner').first()
            self.assertIsNone(owner, "Owner should NOT be created (CSRF protection active)")

    def test_delete_owner_csrf_protected(self):
        """Test that deleting an owner WITHOUT a CSRF token FAILS (400 Bad Request)"""
        self.login()

        # Create an owner to delete
        with self.app.app_context():
            owner = Owner(name="Victim Owner", phone_number="555-1234", store_id=self.store_id)
            db.session.add(owner)
            db.session.commit()
            owner_id = owner.id

        # Try to delete owner WITHOUT CSRF token
        response = self.client.post(f'/owner/{owner_id}/delete', follow_redirects=True)

        # Should FAIL (400 Bad Request) because CSRF protection is active
        self.assertEqual(response.status_code, 400)

        # Verify owner is NOT deleted
        with self.app.app_context():
            owner = db.session.get(Owner, owner_id)
            self.assertIsNotNone(owner, "Owner should NOT be deleted (CSRF protection active)")

    def test_add_owner_with_valid_token(self):
        """Test that adding an owner WITH a valid CSRF token SUCCEEDS"""
        self.login()

        # 1. GET the form to fetch the CSRF token
        response = self.client.get('/add_owner')
        self.assertEqual(response.status_code, 200)

        # Extract token from HTML
        html = response.data.decode('utf-8')
        # Look for <input type="hidden" name="csrf_token" value="...">
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match, "CSRF token not found in add_owner form")
        token = match.group(1)

        # 2. POST with the token
        response = self.client.post('/add_owner', data={
            'name': 'Legitimate Owner',
            'phone': '987-654-3210',
            'csrf_token': token
        }, follow_redirects=True)

        # Should SUCCEED (200 OK)
        self.assertEqual(response.status_code, 200)

        # Verify owner was created
        with self.app.app_context():
            owner = Owner.query.filter_by(name='Legitimate Owner').first()
            self.assertIsNotNone(owner, "Owner should be created with valid token")

if __name__ == '__main__':
    unittest.main()
