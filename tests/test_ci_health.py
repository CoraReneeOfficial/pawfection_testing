import unittest
from unittest.mock import MagicMock, patch
import os
import tempfile
import sys

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
