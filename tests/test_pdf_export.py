import unittest
from unittest.mock import MagicMock, patch
import os
import tempfile
import json
import sys
import datetime

# Add venv/Lib/site-packages to sys.path to load dependencies
sys.path.append(os.path.join(os.getcwd(), 'venv', 'Lib', 'site-packages'))
# Add project root to path
sys.path.append('.')

# Mock binary dependencies to avoid ImportError in this environment
sys.modules['bcrypt'] = MagicMock()
sys.modules['cryptography'] = MagicMock()
sys.modules['cryptography.hazmat'] = MagicMock()
sys.modules['cryptography.hazmat.backends'] = MagicMock()
sys.modules['cryptography.hazmat.primitives'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.serialization'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric'] = MagicMock()
sys.modules['cryptography.hazmat.primitives.asymmetric.rsa'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['googleapiclient'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.errors'] = MagicMock()
sys.modules['google_auth_oauthlib'] = MagicMock()
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['authlib'] = MagicMock()
sys.modules['authlib.integrations'] = MagicMock()
sys.modules['authlib.integrations.flask_client'] = MagicMock()

class TestPDFExport(unittest.TestCase):
    def setUp(self):
        # Mock external dependencies to prevent import errors or side effects
        self.patches = [
            patch('app.migrate_add_remind_at_to_notification'),
            patch('app.stripe'),
            patch('appointments.routes.get_google_service'),
        ]
        for p in self.patches:
            p.start()

        from app import create_app, db
        from models import User, Store, Receipt, Appointment, Dog, Owner

        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SERVER_NAME'] = 'localhost.localdomain'

        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        self.db = db
        self.User = User
        self.Store = Store
        self.Receipt = Receipt
        self.Appointment = Appointment
        self.Dog = Dog
        self.Owner = Owner

        # Configure bcrypt mock
        sys.modules['bcrypt'].hashpw.return_value = b'hashed_password'
        sys.modules['bcrypt'].gensalt.return_value = b'salt'
        sys.modules['bcrypt'].checkpw.return_value = True

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.app_context.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        for p in self.patches:
            p.stop()

    def test_pdf_export_route(self):
        # Create a store and a user
        store = self.Store(name="Test Store", username="teststore", email="store@example.com")
        store.set_password("password")
        store.subscription_status = 'active'
        self.db.session.add(store)
        self.db.session.flush()

        user = self.User(username="testuser", email="user@example.com", store_id=store.id)
        user.set_password("password")
        self.db.session.add(user)
        self.db.session.flush()

        # Create dependencies for Receipt
        owner = self.Owner(name="John", phone_number="123", store_id=store.id)
        self.db.session.add(owner)
        self.db.session.flush()

        dog = self.Dog(name="Fido", owner_id=owner.id, store_id=store.id)
        self.db.session.add(dog)
        self.db.session.flush()

        appt = self.Appointment(
            dog_id=dog.id,
            store_id=store.id,
            created_by_user_id=user.id,
            appointment_datetime=datetime.datetime.now()
        )
        self.db.session.add(appt)
        self.db.session.commit()

        # Create a receipt
        receipt_data = {
            'store_name': 'Test Store',
            'line_items': [{'name': 'Service 1', 'price': 50.0}],
            'subtotal': 50.0,
            'taxes': 5.0,
            'tip': 10.0,
            'total': 65.0,
            'date': '2023-01-01',
            'customer_name': 'John Doe',
            'pet_name': 'Fido'
        }
        receipt = self.Receipt(
            store_id=store.id,
            appointment_id=appt.id,
            receipt_json=json.dumps(receipt_data)
        )
        self.db.session.add(receipt)
        self.db.session.commit()

        # Login
        with self.client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['store_id'] = store.id
            sess['_user_id'] = str(user.id) # Flask-Login

        # Mock FPDF to verify it is called
        with patch('appointments.routes.FPDF') as MockFPDF, \
             patch('appointments.routes.render_template') as mock_render:

            mock_pdf = MagicMock()
            MockFPDF.return_value = mock_pdf
            mock_pdf.output.return_value = b'%PDF-1.4-TEST'

            mock_render.return_value = "<html>Test Receipt</html>"

            # Make request
            response = self.client.get(f'/receipts/export_pdf/{receipt.id}')

            # Verify response
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/pdf')
            self.assertEqual(response.headers['Content-Disposition'], f'attachment; filename=receipt_{receipt.id}.pdf')
            self.assertEqual(response.data, b'%PDF-1.4-TEST')

            # Verify FPDF calls
            MockFPDF.assert_called_once()
            mock_pdf.add_page.assert_called_once()
            mock_pdf.write_html.assert_called_with("<html>Test Receipt</html>")
            mock_pdf.output.assert_called_once()

if __name__ == '__main__':
    unittest.main()
