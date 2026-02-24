
import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Mock dotenv to prevent loading .env file which might contain DATABASE_URL
sys.modules['dotenv'] = MagicMock()

# Mock dependencies that might not be installed or cause issues
try:
    import bcrypt
except ImportError:
    bcrypt_mock = MagicMock()
    bcrypt_mock.hashpw.return_value = b'hashed_password'
    bcrypt_mock.gensalt.return_value = b'salt'
    bcrypt_mock.checkpw.return_value = True
    sys.modules['bcrypt'] = bcrypt_mock

try:
    import cryptography
except ImportError:
    sys.modules['cryptography'] = MagicMock()
    # Mock submodules
    sys.modules['cryptography.hazmat'] = MagicMock()
    sys.modules['cryptography.hazmat.backends'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives'] = MagicMock()

try:
    import authlib
except ImportError:
    sys.modules['authlib'] = MagicMock()
    sys.modules['authlib.integrations'] = MagicMock()
    sys.modules['authlib.integrations.flask_client'] = MagicMock()

try:
    import psycopg2
except ImportError:
    sys.modules['psycopg2'] = MagicMock()

# Unset DATABASE_URL to force SQLite and avoid Postgres connection attempts
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

# Now we can safely import app
from app import create_app, db
from models import User, Store, Owner, Dog, Appointment, Notification, Service
from datetime import datetime

class TestNotificationCleanup(unittest.TestCase):
    def setUp(self):
        # Patch dependencies that might make external calls
        self.patches = []

        # Patch google services
        self.patches.append(patch('appointments.google_calendar_sync.get_google_service', return_value=None))
        self.patches.append(patch('appointments.routes.get_google_service', return_value=None))
        self.patches.append(patch('management.routes.sync_google_calendar_for_store'))

        # Start patches
        for p in self.patches:
            p.start()

        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False # Disable CSRF for tests

        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create Store
        self.store = Store(
            name="Test Store",
            username="teststore",
            email="test@store.com",
            subscription_status='active'
        )
        self.store.set_password("password")
        db.session.add(self.store)
        db.session.commit()

        # Create User
        self.user = User(username="testuser", email="test@user.com", store_id=self.store.id, role="groomer")
        self.user.set_password("password")
        db.session.add(self.user)
        db.session.commit()

        # Create Owner & Dog
        self.owner = Owner(name="Test Owner", phone_number="1234567890", email="owner@test.com", store_id=self.store.id)
        db.session.add(self.owner)
        self.dog = Dog(name="Test Dog", owner=self.owner, store_id=self.store.id)
        db.session.add(self.dog)
        db.session.commit()

        # Create Service
        self.service = Service(name="Test Service", base_price=50.0, store_id=self.store.id)
        db.session.add(self.service)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        for p in self.patches:
            p.stop()

    def test_notification_persists_after_fix(self):
        """
        Verify that fixing an appointment (details_needed -> False) marks the notification as read.
        """
        # 1. Create Appointment with missing details
        appt = Appointment(
            dog_id=self.dog.id,
            appointment_datetime=datetime.now(),
            store_id=self.store.id,
            created_by_user_id=self.user.id,
            details_needed=True,
            requested_services_text=str(self.service.id)
        )
        db.session.add(appt)
        db.session.commit()

        # 2. Create Notification
        notification = Notification(
            store_id=self.store.id,
            type='appointment_needs_review',
            content='Needs review',
            reference_id=appt.id,
            reference_type='appointment',
            is_read=False
        )
        db.session.add(notification)
        db.session.commit()

        # 3. Simulate "Edit Appointment" fixing the issue
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['store_id'] = self.store.id

        # Post data to edit appointment
        response = client.post(f'/appointment/{appt.id}/edit', data={
            'dog_id': self.dog.id,
            'appointment_date': datetime.now().strftime('%Y-%m-%d'),
            'appointment_time': datetime.now().strftime('%H:%M'),
            'services': [str(self.service.id)],
            'groomer_id': self.user.id, # Provide groomer ID to fix it
            'status': 'Scheduled'
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)

        db.session.refresh(appt)
        db.session.refresh(notification)

        # Verify appointment is fixed
        self.assertFalse(appt.details_needed, "Appointment should no longer need details")

        # Verify notification state (Fixed: Should be read)
        self.assertTrue(notification.is_read, "Notification should be marked as read")

    def test_notification_persists_after_delete(self):
        """
        Verify that deleting an appointment deletes the notification.
        """
        appt = Appointment(
            dog_id=self.dog.id,
            appointment_datetime=datetime.now(),
            store_id=self.store.id,
            created_by_user_id=self.user.id,
            details_needed=True,
            requested_services_text=str(self.service.id)
        )
        db.session.add(appt)
        db.session.commit()

        notification = Notification(
            store_id=self.store.id,
            type='appointment_needs_review',
            content='Needs review',
            reference_id=appt.id,
            reference_type='appointment',
            is_read=False
        )
        db.session.add(notification)
        db.session.commit()

        notification_id = notification.id

        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['store_id'] = self.store.id

        response = client.post(f'/appointment/{appt.id}/delete', data={'delete_action': 'delete'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        deleted_appt = db.session.get(Appointment, appt.id)
        self.assertIsNone(deleted_appt)

        notif = db.session.get(Notification, notification_id)
        self.assertIsNone(notif, "Notification should be deleted after appointment deletion")

if __name__ == '__main__':
    unittest.main()
