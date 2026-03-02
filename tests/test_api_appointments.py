import sys
import os
import unittest
from unittest.mock import MagicMock
import json

venv_path = os.path.join(os.getcwd(), 'venv', 'lib', 'python3.11', 'site-packages')
if not os.path.exists(venv_path):
    venv_path = os.path.join(os.getcwd(), 'venv', 'Lib', 'site-packages')
if os.path.exists(venv_path) and venv_path not in sys.path:
    sys.path.insert(0, venv_path)

sys.modules['bcrypt'] = MagicMock()
google_mock = MagicMock()
google_mock.__path__ = []
sys.modules['google'] = google_mock
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()

googleapiclient_mock = MagicMock()
googleapiclient_mock.__path__ = []
sys.modules['googleapiclient'] = googleapiclient_mock
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.errors'] = MagicMock()
sys.modules['google_auth_oauthlib'] = MagicMock()
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['fpdf'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()
sys.modules['dotenv'] = MagicMock()
sys.modules['ollama'] = MagicMock()
sys.modules['markdown'] = MagicMock()

crypto_mock = MagicMock()
sys.modules['cryptography'] = crypto_mock
sys.modules['cryptography.hazmat'] = crypto_mock
sys.modules['cryptography.hazmat.backends'] = crypto_mock
sys.modules['cryptography.hazmat.primitives'] = crypto_mock
sys.modules['cryptography.hazmat.primitives.asymmetric'] = crypto_mock
sys.modules['cryptography.hazmat.primitives.asymmetric.rsa'] = crypto_mock
sys.modules['cryptography.hazmat.primitives.asymmetric.ec'] = crypto_mock
sys.modules['cryptography.x509'] = crypto_mock

authlib_mock = MagicMock()
sys.modules['authlib'] = authlib_mock
sys.modules['authlib.integrations'] = authlib_mock
sys.modules['authlib.integrations.flask_client'] = authlib_mock

stripe_mock = MagicMock()
sys.modules['stripe'] = stripe_mock

os.environ['DATABASE_URL'] = 'sqlite:///:memory:' # Use in-memory sqlite for test

from app import create_app
from extensions import db
from models import User, Store, Dog, Owner, Appointment
import datetime

class TestApiAppointments(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.store = Store(name='Test Store', username='teststore', subscription_status='active', password_hash='hash')
        db.session.add(self.store)
        db.session.commit()

        self.user = User(username='testadmin', email='test@example.com', store_id=self.store.id, is_admin=True, role='admin', password_hash='hash')
        db.session.add(self.user)
        db.session.commit()

        self.owner = Owner(name='Jane Smith', phone_number='1234567890', store_id=self.store.id)
        db.session.add(self.owner)
        db.session.commit()

        self.dog = Dog(name='Buddy', owner_id=self.owner.id, store_id=self.store.id)
        db.session.add(self.dog)
        db.session.commit()

        self.appointment = Appointment(
            dog_id=self.dog.id,
            store_id=self.store.id,
            created_by_user_id=self.user.id,
            appointment_datetime=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
            status='Scheduled'
        )
        db.session.add(self.appointment)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_search_appointments_api(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['store_id'] = self.store.id

        response = self.client.get('/api/appointments/search?q=Jane')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['customer']['name'], 'Jane Smith')
        self.assertEqual(data[0]['pet']['name'], 'Buddy')

if __name__ == '__main__':
    unittest.main()
