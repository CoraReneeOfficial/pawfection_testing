import unittest
from unittest.mock import MagicMock, patch
import os
import tempfile
import sys

# Add venv/Lib/site-packages to sys.path to load dependencies
# Keep this for local dev compatibility
sys.path.append(os.path.join(os.getcwd(), 'venv', 'Lib', 'site-packages'))
# Add project root to path
sys.path.append('.')

# Unset DATABASE_URL to force SQLite and avoid Postgres connection attempts
# which fail when psycopg2 is mocked or missing in this environment.
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

from flask import url_for

# Mock dotenv to prevent loading .env file which might contain DATABASE_URL
# causing create_app to try connecting to Postgres
sys.modules['dotenv'] = MagicMock()

# Conditionally mock dependencies
# If import fails (e.g. locally missing or broken), we use MagicMock.
# In CI (where requirements are installed), we use the real library.

try:
    import bcrypt
except ImportError:
    sys.modules['bcrypt'] = MagicMock()
    # Configure bcrypt mock for basic usage
    sys.modules['bcrypt'].hashpw.return_value = b'hashed_password'
    sys.modules['bcrypt'].gensalt.return_value = b'salt'
    sys.modules['bcrypt'].checkpw.return_value = True

try:
    import cryptography
except ImportError:
    sys.modules['cryptography'] = MagicMock()
    sys.modules['cryptography.x509'] = MagicMock()
    sys.modules['cryptography.hazmat'] = MagicMock()
    sys.modules['cryptography.hazmat.backends'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.serialization'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.asymmetric'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.asymmetric.rsa'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.asymmetric.ec'] = MagicMock()

    # Also mock authlib if cryptography is missing/broken, as authlib depends on it
    sys.modules['authlib'] = MagicMock()
    sys.modules['authlib.integrations'] = MagicMock()
    sys.modules['authlib.integrations.flask_client'] = MagicMock()
    sys.modules['authlib.jose'] = MagicMock()
    sys.modules['authlib.jose.rfc7517'] = MagicMock()
    sys.modules['authlib.jose.rfc7518'] = MagicMock()

try:
    import google.oauth2
    import googleapiclient
    import google_auth_oauthlib
    import google.auth
except ImportError:
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
    # Fix for SQLAlchemy expecting an exception class
    class MockError(Exception): pass
    sys.modules['psycopg2'].Error = MockError

try:
    import pandas
except ImportError:
    sys.modules['pandas'] = MagicMock()

try:
    import fpdf
except ImportError:
    sys.modules['fpdf'] = MagicMock()

try:
    import xlsxwriter
except ImportError:
    sys.modules['xlsxwriter'] = MagicMock()

try:
    import psutil
except ImportError:
    sys.modules['psutil'] = MagicMock()

class TestCIHealth(unittest.TestCase):
    def setUp(self):
        # Patch the migration script to do nothing to avoid side effects on the file system
        self.migrate_patcher = patch('app.migrate_add_remind_at_to_notification')
        self.mock_migrate = self.migrate_patcher.start()

        # Patch stripe to avoid API key issues during app creation/request
        self.stripe_patcher = patch('app.stripe')
        self.mock_stripe = self.stripe_patcher.start()

        # Patch Google Calendar service to avoid API calls
        self.gcal_patcher = patch('appointments.google_calendar_sync.get_google_service')
        self.mock_gcal = self.gcal_patcher.start()
        self.mock_gcal.return_value = None # Simulate no service or failure to connect

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
        self.gcal_patcher.stop()

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

    def test_all_routes_smoke(self):
        """Smoke test to check all GET routes don't crash."""
        # Create a superadmin user to access restricted routes
        sa = self.User(username='superadmin', role='superadmin', email='sa@example.com')
        sa.set_password('password')
        self.db.session.add(sa)
        self.db.session.commit()

        # Log in as superadmin
        with self.client:
            self.client.post('/superadmin/login', data={'username': 'superadmin', 'password': 'password'})

            # Iterate routes
            # Use test_request_context for url_for to work
            count = 0
            for rule in self.app.url_map.iter_rules():
                # Only check GET requests
                if 'GET' in rule.methods and not rule.rule.startswith('/static'):
                    endpoint = rule.endpoint

                    # Skip logout (redirects) and delete endpoints
                    # Also skip google auth callbacks as they require complex mocking of the auth flow
                    if 'logout' in endpoint or 'delete' in endpoint or 'google' in endpoint:
                        continue

                    # Prepare dummy arguments
                    kwargs = {}
                    for arg in rule.arguments:
                        # Pass 1 for all IDs/arguments
                        kwargs[arg] = 1

                    try:
                        # Generate URL
                        with self.app.test_request_context():
                            try:
                                url = url_for(endpoint, **kwargs)
                            except Exception:
                                # Skip routes where url generation fails (e.g. complex types)
                                continue

                        # Make request
                        response = self.client.get(url)
                        count += 1

                        # Assert no server error (500)
                        self.assertNotEqual(response.status_code, 500, f"Route {endpoint} ({url}) failed with 500 Internal Server Error")

                    except Exception as e:
                         self.fail(f"Route {endpoint} raised exception during test: {e}")

            print(f"Checked {count} routes successfully.")

if __name__ == '__main__':
    unittest.main()
