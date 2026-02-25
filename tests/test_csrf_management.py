import unittest
from unittest.mock import MagicMock
import sys
import os

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

# Removed google mocks since dependencies are installed

# Prevent database connection attempt in app.py if it tries to load from env
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

from app import create_app, db
from models import User, Store, Service

class TestCSRFManagement(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = True  # Enable CSRF
        # Ensure default check is OFF (as in app.py) so we can prove manual protect() is needed
        self.app.config['WTF_CSRF_CHECK_DEFAULT'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create a store
            store = Store(name="Test Store", username="teststore", email="test@example.com")
            store.set_password("password")
            store.tax_enabled = False # Explicitly set to False for testing
            db.session.add(store)
            db.session.commit()
            self.store_id = store.id

            # Create an admin user
            user = User(username='admin', role='admin', is_admin=True, store_id=self.store_id, email="admin@example.com")
            user.set_password('password')
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id

            # Create a service to delete
            service = Service(name="Test Service", base_price=10.0, store_id=self.store_id)
            db.session.add(service)
            db.session.commit()
            self.service_id = service.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['store_id'] = self.store_id
            sess['_fresh'] = True

    def test_delete_service_csrf_protected(self):
        """Test that deleting a service WITHOUT a CSRF token fails (400 Bad Request)"""
        self.login()

        # Verify service exists before deletion
        with self.app.app_context():
            service = db.session.get(Service, self.service_id)
            self.assertIsNotNone(service)

        # Try to delete service WITHOUT CSRF token
        response = self.client.post(f'/manage/services/{self.service_id}/delete', follow_redirects=True)

        # Should now fail with 400 Bad Request because of csrf.protect()
        self.assertEqual(response.status_code, 400)

        # Verify service is NOT gone
        with self.app.app_context():
            service = db.session.get(Service, self.service_id)
            self.assertIsNotNone(service, "Service should NOT be deleted (CSRF protection active)")

    def test_toggle_taxes_csrf_protected(self):
        """Test that toggling taxes WITHOUT a CSRF token fails (400 Bad Request)"""
        self.login()

        # Verify initial state
        with self.app.app_context():
            store = db.session.get(Store, self.store_id)
            self.assertFalse(store.tax_enabled)

        # Try to toggle taxes WITHOUT CSRF token
        response = self.client.post('/manage/toggle_taxes', data={'tax_enabled': 'on'}, follow_redirects=True)

        # Should fail with 400 Bad Request
        self.assertEqual(response.status_code, 400)

        with self.app.app_context():
            store = db.session.get(Store, self.store_id)
            self.assertFalse(store.tax_enabled, "Taxes should NOT be toggled (CSRF protection active)")
