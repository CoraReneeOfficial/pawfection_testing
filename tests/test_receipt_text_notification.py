import sys
import os
import unittest
import json
from unittest.mock import MagicMock, patch

# Add venv to path if not present (for running in restricted environment)
venv_path = os.path.join(os.getcwd(), 'venv', 'lib', 'python3.11', 'site-packages')
if not os.path.exists(venv_path):
    venv_path = os.path.join(os.getcwd(), 'venv', 'Lib', 'site-packages')
if os.path.exists(venv_path) and venv_path not in sys.path:
    sys.path.insert(0, venv_path)

# Mock binary modules or unavailable dependencies
sys.modules['bcrypt'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['googleapiclient'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.errors'] = MagicMock()
sys.modules['googleapiclient.http'] = MagicMock()
sys.modules['google_auth_oauthlib'] = MagicMock()
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['fpdf'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()
sys.modules['dotenv'] = MagicMock() # Prevent loading .env
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL'] # Ensure no DB connection attempt
sys.modules['cryptography'] = MagicMock()
sys.modules['cryptography.hazmat'] = MagicMock()
sys.modules['cryptography.hazmat.backends'] = MagicMock()
sys.modules['cryptography.hazmat.primitives'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.serialization'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric.rsa'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric.ec'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric.ed25519'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric.ed448'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric.x25519'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric.x448'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric.utils'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.ciphers'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.ciphers.algorithms'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.ciphers.modes'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.hashes'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.hmac'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.kdf'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.kdf.concatkdf'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.keywrap'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.padding'] = MagicMock()
sys.modules['cryptography.exceptions'] = MagicMock()
sys.modules['cryptography.x509'] = MagicMock()

import tempfile
import datetime
from datetime import timezone

# Import necessary modules
from app import create_app
from extensions import db
from models import User, Store, Owner, Dog, Appointment

class TestReceiptTextNotification(unittest.TestCase):
    def setUp(self):
        # Patch migrations and stripe
        self.migrate_patcher = patch('app.migrate_add_remind_at_to_notification')
        self.mock_migrate = self.migrate_patcher.start()

        self.stripe_patcher = patch('app.stripe')
        self.mock_stripe = self.stripe_patcher.start()

        self.db_fd, self.db_path = tempfile.mkstemp()

        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SERVER_NAME'] = 'localhost'
        self.app.config['SECRET_KEY'] = 'test_secret'

        self.client = self.app.test_client()
        self.app_ctx = self.app.app_context()
        self.app_ctx.push()

        db.create_all()
        self.create_test_data()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_ctx.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        self.migrate_patcher.stop()
        self.stripe_patcher.stop()

    def create_test_data(self):
        # Create Store with Google Token (required for email sending)
        self.store = Store(
            name="Test Store",
            username="teststore",
            email="store@test.com",
            subscription_status="active",
            google_token_json=json.dumps({
                "token": "fake_token",
                "refresh_token": "fake_refresh",
                "client_id": "fake_client",
                "client_secret": "fake_secret",
                "sender_email": "store@test.com"
            })
        )
        self.store.password_hash = "mock_hash"
        db.session.add(self.store)
        db.session.commit()

        # Create User
        self.user = User(
            username="testuser",
            role="admin",
            store_id=self.store.id,
            is_admin=True,
            is_groomer=True
        )
        self.user.password_hash = "mock_hash"
        db.session.add(self.user)
        db.session.commit()

        # Create Owner with Text Notifications Enabled
        self.owner = Owner(
            name="John Doe",
            phone_number="1234567890",
            email="john@example.com",
            store_id=self.store.id,
            text_notifications_enabled=True,
            phone_carrier="Verizon"  # Should map to vzwpix.com
        )
        db.session.add(self.owner)
        db.session.commit()

        # Create Dog
        self.dog = Dog(
            name="Fido",
            owner_id=self.owner.id,
            store_id=self.store.id
        )
        db.session.add(self.dog)
        db.session.commit()

        # Create Appointment
        self.appointment = Appointment(
            dog_id=self.dog.id,
            appointment_datetime=datetime.datetime.now(timezone.utc),
            status="Scheduled",
            created_by_user_id=self.user.id,
            groomer_id=self.user.id,
            store_id=self.store.id
        )
        db.session.add(self.appointment)
        db.session.commit()

    @patch('notifications.email_utils.get_google_service')
    def test_finalize_checkout_sends_notification(self, mock_get_google_service):
        """Test that finalize_checkout calls Google Service to send notification."""
        # Setup mock service
        mock_service = MagicMock()
        mock_get_google_service.return_value = mock_service

        # Mock the chain: service.users().messages().send().execute()
        mock_users = mock_service.users.return_value
        mock_messages = mock_users.messages.return_value
        mock_send = mock_messages.send.return_value
        mock_send.execute.return_value = {'id': '12345'}

        # Login and set session
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['store_id'] = self.store.id
            sess['checkout_data'] = {
                'appointment_id': self.appointment.id,
                'customer_name': self.owner.name,
                'pet_name': self.dog.name,
                'line_items': [{'name': 'Bath', 'price': 50.0}],
                'subtotal': 50.0,
                'tip_amount': 10.0,
                'taxes': 5.0,
                'total': 65.0,
                'payment_method': 'cash',
                'receipt_id': 'RCP-TEST-123'
            }

        # Perform checkout finalization
        response = self.client.post(
            f'/finalize_checkout/{self.appointment.id}',
            follow_redirects=False
        )

        # Assert redirection to dashboard
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard', response.location)

        # Assert that get_google_service was called (meaning it tried to send email)
        self.assertTrue(mock_get_google_service.called, "get_google_service was not called")

        # Assert that messages.send was called
        # We expect at least one call (email or text or both). Since owner has both enabled, likely both.
        self.assertTrue(mock_send.execute.called, "messages.send().execute() was not called")

        # Verify call count. Owner has email and text enabled. Code attempts both.
        # Should be called 2 times.
        self.assertEqual(mock_send.execute.call_count, 2)

if __name__ == '__main__':
    unittest.main()
