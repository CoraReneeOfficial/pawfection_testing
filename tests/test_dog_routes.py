import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import tempfile

class TestDogRoutes(unittest.TestCase):
    def setUp(self):
        # --- Handle Environment & Dependencies ---

        # 1. Modify sys.path for this specific environment (Windows venv on Linux compat)
        # Store original path to restore later
        self.original_sys_path = sys.path.copy()
        venv_site_packages = os.path.abspath("venv/Lib/site-packages")
        if os.path.exists(venv_site_packages) and venv_site_packages not in sys.path:
            sys.path.append(venv_site_packages)

        # 2. Configure Mocks for Binary Dependencies
        # Create mocks dictionary
        self.mocks = {
            'bcrypt': MagicMock(),
            'authlib': MagicMock(),
            'authlib.integrations': MagicMock(),
            'authlib.integrations.flask_client': MagicMock(),
            'google': MagicMock(),
            'google.auth': MagicMock(),
            'google.auth.transport': MagicMock(),
            'google.auth.transport.requests': MagicMock(),
            'google.oauth2': MagicMock(),
            'google.oauth2.credentials': MagicMock(),
            'google_auth_oauthlib': MagicMock(),
            'google_auth_oauthlib.flow': MagicMock(),
            'googleapiclient': MagicMock(),
            'googleapiclient.discovery': MagicMock(),
            'googleapiclient.errors': MagicMock(),
            # Include cryptography mocks just in case authlib leaks through
            'cryptography': MagicMock(),
            'cryptography.hazmat': MagicMock(),
            'cryptography.hazmat.backends': MagicMock(),
            'cryptography.hazmat.primitives': MagicMock(),
            'cryptography.hazmat.primitives.asymmetric': MagicMock(),
            'cryptography.hazmat.primitives.asymmetric.ec': MagicMock(),
            'cryptography.hazmat.primitives.asymmetric.rsa': MagicMock(),
            'cryptography.hazmat.primitives.serialization': MagicMock(),
            'cryptography.hazmat.primitives.ciphers': MagicMock(),
            'cryptography.hazmat.primitives.hashes': MagicMock(),
            'cryptography.hazmat.primitives.kdf': MagicMock(),
            'cryptography.hazmat.primitives.padding': MagicMock(),
            'cryptography.hazmat.primitives.hmac': MagicMock(),
            'cryptography.x509': MagicMock(),
        }

        # Configure mock behavior (bcrypt needs to return bytes for hashpw)
        self.mocks['bcrypt'].gensalt.return_value = b'salt'
        self.mocks['bcrypt'].hashpw.side_effect = lambda pw, salt: pw + salt
        self.mocks['bcrypt'].checkpw.return_value = True

        # Apply sys.modules patch
        self.modules_patcher = patch.dict(sys.modules, self.mocks)
        self.modules_patcher.start()

        # 3. Patch application-specific modules
        # Patch the migration script to do nothing to avoid side effects on the file system
        self.migrate_patcher = patch('app.migrate_add_remind_at_to_notification')
        self.mock_migrate = self.migrate_patcher.start()

        # Patch stripe to avoid API key issues during app creation/request
        self.stripe_patcher = patch('app.stripe')
        self.mock_stripe = self.stripe_patcher.start()

        # --- Initialize App Context ---

        # Import app inside setUp to ensure we are using the environment context with patches applied
        from app import create_app, db
        from models import User, Store

        # Create a temporary file to use as a database
        self.db_fd, self.db_path = tempfile.mkstemp()

        # Configure the app for testing
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for easier testing
        self.app.config['SERVER_NAME'] = 'localhost.localdomain'

        # Create a test client
        self.client = self.app.test_client()

        # Push application context
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Initialize the database
        db.create_all()
        self.db = db
        self.User = User
        self.Store = Store

    def tearDown(self):
        # Cleanup database
        self.db.session.remove()
        self.db.drop_all()
        self.app_context.pop()

        # Close and remove the temporary database file
        os.close(self.db_fd)
        os.unlink(self.db_path)

        # Stop patches
        self.migrate_patcher.stop()
        self.stripe_patcher.stop()
        self.modules_patcher.stop()

        # Restore sys.path
        sys.path = self.original_sys_path

    def test_debug_user_store(self):
        """Debug test to check user store association"""
        # Create a user
        u = self.User(username='testuser', email='test@example.com')
        u.set_password('password')
        self.db.session.add(u)
        self.db.session.commit()

        # Create a store
        s = self.Store(name='Test Store', username='storeuser', email='store@example.com')
        s.set_password('storepass')
        self.db.session.add(s)
        self.db.session.commit()

        # Associate user with store
        u.store_id = s.id
        self.db.session.commit()

        # Verify association via ORM
        # Reload user from DB to ensure session state is clean
        fetched_user = self.User.query.filter_by(username='testuser').first()
        self.assertIsNotNone(fetched_user)
        self.assertIsNotNone(fetched_user.store)
        self.assertEqual(fetched_user.store.name, 'Test Store')
        self.assertEqual(fetched_user.store.email, 'store@example.com')

if __name__ == '__main__':
    unittest.main()
