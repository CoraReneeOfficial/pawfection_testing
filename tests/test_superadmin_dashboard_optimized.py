import unittest
from unittest.mock import patch, MagicMock
import sys
import os

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

class MockModule(MagicMock):
    @classmethod
    def __getattr__(cls, name):
        return MagicMock()

# Mock ALL the problem dependencies
for m in [
    'authlib', 'authlib.integrations', 'authlib.integrations.flask_client',
    'dotenv', 'google', 'google.genai', 'google.oauth2', 'google.oauth2.credentials',
    'google.auth', 'google.auth.transport', 'google.auth.transport.requests',
    'googleapiclient', 'googleapiclient.discovery', 'googleapiclient.errors',
    'bcrypt', 'psutil', 'fpdf', 'markdown', 'pandas', 'xlsxwriter', 'stripe'
]:
    sys.modules[m] = MockModule()

sys.modules['bcrypt'].hashpw = lambda p, s: b'hashed_password'
sys.modules['bcrypt'].gensalt = lambda: b'salt'
sys.modules['bcrypt'].checkpw = lambda p, h: True

from app import create_app
from extensions import db
from models import User, Store, ActivityLog

class TestSuperadminDashboardOptimized(unittest.TestCase):
    def setUp(self):
        # Setup application context
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()

        # Create a test store and user
        self.store = Store(name='Test Store', username='teststore', email='test@store.com', subscription_status='active')
        self.store.set_password('password')
        db.session.add(self.store)
        db.session.flush()

        self.superadmin = User(username='superadmin', email='super@admin.com', role='superadmin', is_admin=True)
        self.superadmin.set_password('password')
        db.session.add(self.superadmin)
        db.session.flush()

        self.user = User(username='testadmin', email='admin@test.com', role='admin', store_id=self.store.id, is_admin=True)
        self.user.set_password('password')
        db.session.add(self.user)
        db.session.flush()

        # Create activity log
        log = ActivityLog(user_id=self.user.id, store_id=self.store.id, action='Logged in')
        db.session.add(log)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()


    def test_superadmin_dashboard_loads_without_error(self):


        # Access dashboard
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.superadmin.id
            sess['is_superadmin'] = True

        response = self.client.get('/superadmin/dashboard', follow_redirects=True)

        # Since it might redirect because of a Before_Request hook looking at real session instead of app.session,
        # or maybe the test needs to mock the g.user.

        print("Response Status:", response.status_code)
        if response.status_code == 302:
            print("Redirect location:", response.headers.get('Location'))

        # Check output contains 'testadmin' and 'Test Store'
        html = response.data.decode('utf-8')
        self.assertIn('testadmin', html)
        self.assertIn('Test Store', html)
        self.assertIn('Logged in', html)

if __name__ == '__main__':
    unittest.main()
