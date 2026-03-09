import sys
import os
import unittest
from unittest.mock import MagicMock

# Mock dependencies
sys.modules['bcrypt'] = MagicMock()
sys.modules['google'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()
sys.modules['googleapiclient'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.errors'] = MagicMock()
sys.modules['google_auth_oauthlib'] = MagicMock()
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['fpdf'] = MagicMock()
sys.modules['dotenv'] = MagicMock()
sys.modules['ollama'] = MagicMock()
sys.modules['markdown'] = MagicMock()
sys.modules['cryptography'] = MagicMock()
sys.modules['authlib'] = MagicMock()
sys.modules['authlib.integrations'] = MagicMock()
sys.modules['authlib.integrations.flask_client'] = MagicMock()
sys.modules['stripe'] = MagicMock()

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app
from extensions import db
from models import User, Store, ActivityLog

class TestLogsRoute(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
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

        self.log1 = ActivityLog(action="Test Action", store_id=self.store.id, user_id=self.user.id)
        db.session.add(self.log1)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_logs_route(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['store_id'] = self.store.id

        response = self.client.get('/logs')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Test Action', response.data)

if __name__ == '__main__':
    unittest.main()
