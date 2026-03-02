import sys
import os
import unittest
from unittest.mock import MagicMock
import io
import json

# Add Windows venv site-packages to path
site_packages = os.path.abspath('venv/Lib/site-packages')
if site_packages not in sys.path:
    sys.path.insert(0, site_packages)

# Mock binary dependencies
sys.modules['bcrypt'] = MagicMock()
sys.modules['bcrypt'].hashpw.return_value = b'hashed_password'
sys.modules['bcrypt'].gensalt.return_value = b'salt'
sys.modules['bcrypt'].checkpw.return_value = True
sys.modules['cryptography'] = MagicMock()

# Google Mocks
sys.modules['google'] = MagicMock()
sys.modules['google'].__path__ = []
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['google.appengine'] = MagicMock()
sys.modules['google.appengine.api'] = MagicMock()
sys.modules['googleapiclient'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.errors'] = MagicMock()

sys.modules['authlib'] = MagicMock()
sys.modules['authlib.integrations'] = MagicMock()
sys.modules['authlib.integrations.flask_client'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()
sys.modules['psutil'] = MagicMock()

# Mock other potential missing libs
sys.modules['fpdf'] = MagicMock()
sys.modules['markdown'] = MagicMock()
sys.modules['pandas'] = MagicMock()
sys.modules['xlsxwriter'] = MagicMock()
sys.modules['ollama'] = MagicMock()

# FORCE Mock dotenv to prevent loading .env
sys.modules['dotenv'] = MagicMock()
sys.modules['dotenv'].load_dotenv = MagicMock()

# Mock migration script to prevent touching real DB file
sys.modules['migrate_add_remind_at_to_notification'] = MagicMock()

# Set DATABASE_URL to memory to override file-based DB in create_app
os.environ['DATABASE_URL'] = 'sqlite://'

# Now import app
try:
    from app import create_app, db
    from models import User, Store
except ImportError as e:
    print(f"ImportError: {e}")
    print(f"sys.path: {sys.path}")
    raise

class DataManagementTestCase(unittest.TestCase):
    def setUp(self):
        os.environ['FLASK_SECRET_KEY'] = 'test_key'
        os.environ['STRIPE_PUBLISHABLE_KEY'] = 'pk_test'
        os.environ['STRIPE_SECRET_KEY'] = 'sk_test'

        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create a Store
            self.store = Store(name='Test Store', username='teststore', email='test@example.com')
            self.store.password_hash = 'hashed_password'
            db.session.add(self.store)
            db.session.commit()
            self.store_id = self.store.id

            # Create a Store Admin user
            self.admin_user = User(username='storeadmin', email='admin@example.com',
                                 role='admin', is_admin=True, store_id=self.store.id)
            self.admin_user.password_hash = 'hashed_password'
            db.session.add(self.admin_user)
            db.session.commit()
            self.admin_user_id = self.admin_user.id

            # Create a normal user
            self.normal_user = User(username='normaluser', email='normal@example.com',
                                 role='staff', is_admin=False, store_id=self.store.id)
            self.normal_user.password_hash = 'hashed_password'
            db.session.add(self.normal_user)
            db.session.commit()
            self.normal_user_id = self.normal_user.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_admin_can_access_data_management(self):
        with self.client.session_transaction() as sess:
            sess['store_id'] = self.store_id
            sess['user_id'] = self.admin_user_id

        response = self.client.get('/manage/data')
        self.assertEqual(response.status_code, 200)

    def test_normal_user_cannot_access_data_management(self):
        with self.client.session_transaction() as sess:
            sess['store_id'] = self.store_id
            sess['user_id'] = self.normal_user_id

        response = self.client.get('/manage/data', follow_redirects=False)
        self.assertNotEqual(response.status_code, 200)

    def test_export_database_json(self):
        with self.client.session_transaction() as sess:
            sess['store_id'] = self.store_id
            sess['user_id'] = self.admin_user_id

        response = self.client.get('/manage/data/export/database')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/json')

        # Verify JSON structure
        data = json.loads(response.data)
        self.assertIn('metadata', data)
        self.assertIn('store', data)
        self.assertIn('users', data)

        # Verify only current store data is present
        self.assertEqual(data['store'][0]['id'], self.store_id)

    def test_import_database_json(self):
        with self.client.session_transaction() as sess:
            sess['store_id'] = self.store_id
            sess['user_id'] = self.admin_user_id

        # Prepare dummy json backup
        dummy_backup = {
            'metadata': {'version': '1.0'},
            'owners': [
                {'id': 1, 'first_name': 'Test', 'last_name': 'Owner', 'email': 'new@example.com'}
            ]
        }

        data = {
            'database_file': (io.BytesIO(json.dumps(dummy_backup).encode('utf-8')), 'backup.json'),
            'import_mode': 'merge'
        }

        response = self.client.post('/manage/data/import_database', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        # We just check it didn't 500
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
