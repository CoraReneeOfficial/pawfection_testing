import sys
import os
import unittest
from unittest.mock import MagicMock

# Add venv to path if not present (for running in restricted environment)
# Trying typical Linux path first, then Windows structure if needed
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
import json
import datetime
from datetime import timezone
from unittest.mock import patch, MagicMock

# Import necessary modules
from flask import session
from app import create_app
from extensions import db
from models import User, Store, Owner, Dog, Appointment, Receipt

class TestCheckoutFinalize(unittest.TestCase):
    def setUp(self):
        # Patch migrations and stripe to avoid side effects
        self.migrate_patcher = patch('app.migrate_add_remind_at_to_notification')
        self.mock_migrate = self.migrate_patcher.start()

        self.stripe_patcher = patch('app.stripe')
        self.mock_stripe = self.stripe_patcher.start()

        # Create a temporary file to use as a database
        self.db_fd, self.db_path = tempfile.mkstemp()

        # Configure the app for testing
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF
        self.app.config['SERVER_NAME'] = 'localhost'
        self.app.config['SECRET_KEY'] = 'test_secret'

        # Create test client
        self.client = self.app.test_client()

        # Push application context
        self.app_ctx = self.app.app_context()
        self.app_ctx.push()

        # Initialize the database
        db.create_all()

        # Create test data
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
        # Create Store
        self.store = Store(
            name="Test Store",
            username="teststore",
            email="store@test.com",
            subscription_status="active"
        )
        # Mock set_password since bcrypt is mocked
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

        # Create Owner
        self.owner = Owner(
            name="John Doe",
            phone_number="1234567890",
            email="john@example.com",
            store_id=self.store.id
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

    def test_finalize_checkout_success(self):
        """Test the finalize_checkout route with valid data."""
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

        response = self.client.post(
            f'/finalize_checkout/{self.appointment.id}',
            follow_redirects=False
        )

        # Should redirect to dashboard
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard', response.location)

        # Verify DB updates
        updated_appt = db.session.get(Appointment, self.appointment.id)
        self.assertEqual(updated_appt.status, 'Completed')
        self.assertEqual(updated_appt.checkout_total_amount, 65.0)

        # Verify Receipt created
        receipt = Receipt.query.filter_by(appointment_id=self.appointment.id).first()
        self.assertIsNotNone(receipt)
        receipt_data = json.loads(receipt.receipt_json)
        self.assertEqual(receipt_data['total'], 65.0)

    def test_finalize_checkout_missing_checkout_data(self):
        """Test redirect if checkout_data is missing."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['store_id'] = self.store.id
            # No checkout_data

        response = self.client.post(
            f'/finalize_checkout/{self.appointment.id}',
            follow_redirects=False # Should redirect to checkout_start
        )

        self.assertEqual(response.status_code, 302)
        # The location might be relative or absolute.
        self.assertTrue('/select_checkout' in response.location)

if __name__ == '__main__':
    unittest.main()
