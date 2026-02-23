
import unittest
from unittest.mock import MagicMock, patch
import os
import tempfile
import sys

# Add venv/Lib/site-packages to sys.path to load dependencies
sys.path.append(os.path.join(os.getcwd(), 'venv', 'Lib', 'site-packages'))
# Add project root to path
sys.path.append('.')

# Mock binary dependencies to avoid ImportError in this environment
sys.modules['bcrypt'] = MagicMock()
# Configure bcrypt mock
sys.modules['bcrypt'].hashpw.return_value = b'hashed_password'
sys.modules['bcrypt'].gensalt.return_value = b'salt'
sys.modules['bcrypt'].checkpw.return_value = True

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

# Additional mocks needed for CI environment
sys.modules['fpdf'] = MagicMock()
sys.modules['pandas'] = MagicMock()
sys.modules['xlsxwriter'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.binary'] = MagicMock()
sys.modules['psutil'] = MagicMock()

# Unset DATABASE_URL to avoid connecting to production DB during import
# Save it to restore later if needed (though os.environ changes are process-local)
original_db_url = os.environ.get('DATABASE_URL')
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

class TestCIHealth(unittest.TestCase):
    def setUp(self):
        # Patch the migration script to do nothing to avoid side effects on the file system
        self.migrate_patcher = patch('app.migrate_add_remind_at_to_notification')
        self.mock_migrate = self.migrate_patcher.start()

        # Patch stripe to avoid API key issues during app creation/request
        self.stripe_patcher = patch('app.stripe')
        self.mock_stripe = self.stripe_patcher.start()

        # Import app inside setUp to ensure we are using the environment context
        # In a real CI run, requirements are installed so imports should work.
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

    def test_health_check(self):
        """Basic health check: can we fetch the home page?"""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        # Check for expected content (e.g., app name)
        # Assuming 'Pawfection' is somewhere in the home page
        self.assertIn(b'Pawfection', response.data)

    def test_database_integration(self):
        """Can we write and read from the DB?"""
        u = self.User(username='healthcheck', email='health@example.com')
        u.set_password('health')
        self.db.session.add(u)
        self.db.session.commit()

        fetched = self.User.query.filter_by(username='healthcheck').first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.email, 'health@example.com')

    def test_initial_setup_redirect(self):
        """Test that accessing login with empty DB redirects to initial setup."""
        response = self.client.get('/login')
        # Should redirect to initial setup because no users exist
        self.assertEqual(response.status_code, 302)
        self.assertIn('/initial_setup', response.location)

    def test_store_login_redirect(self):
        """Test that if user exists but no store selected, redirects to store login."""
        # Create a user so we aren't sent to initial setup
        u = self.User(username='admin', email='admin@example.com')
        u.set_password('password')
        self.db.session.add(u)
        self.db.session.commit()

        response = self.client.get('/login')
        # Should redirect to store login because session['store_id'] is empty
        self.assertEqual(response.status_code, 302)
        self.assertIn('/store/login', response.location)

    def test_initial_setup_page(self):
        """Test that the initial setup page loads successfully."""
        response = self.client.get('/initial_setup')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'setup', response.data.lower())

if __name__ == '__main__':
    unittest.main()
