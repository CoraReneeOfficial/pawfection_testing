import sys
import os
import unittest
from unittest.mock import MagicMock

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
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()

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
sys.modules['pandas'] = MagicMock()
sys.modules['xlsxwriter'] = MagicMock()

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

import io

class SecurityDBImportTestCase(unittest.TestCase):
    def setUp(self):
        # Set env vars required for app config
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

            # Create a Superadmin user
            self.superadmin_user = User(username='superadmin', email='super@example.com',
                                      role='superadmin', is_admin=True, store_id=None)
            self.superadmin_user.password_hash = 'hashed_password'
            db.session.add(self.superadmin_user)

            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_store_admin_cannot_import_database(self):
        # Log in as Store Admin by setting session directly
        with self.client.session_transaction() as sess:
            sess['store_id'] = self.store_id
            sess['user_id'] = self.admin_user_id
            # Note: No 'is_superadmin' in session for store admin

        # Prepare a dummy file
        data = {
            'database_file': (io.BytesIO(b"dummy content"), 'test.db'),
            'import_mode': 'overwrite'
        }

        # Try to POST to import_database
        response = self.client.post('/data_management/import_database', data=data, content_type='multipart/form-data', follow_redirects=True)

        # Assert that we ARE blocked by role check
        self.assertIn(b'Only Superadmins can import', response.data)

        # Assert that it did NOT try to import (so no error about invalid db file)
        self.assertNotIn(b'Error importing database', response.data)

if __name__ == '__main__':
    unittest.main()
