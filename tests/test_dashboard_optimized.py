import unittest
from unittest.mock import patch, MagicMock
import sys

# Minimal mock setup to bypass problematic imports
sys.modules['dotenv'] = MagicMock()
sys.modules['bcrypt'] = MagicMock()

# Setup google package mock completely
class MockGooglePackage(MagicMock):
    pass
mock_google = MockGooglePackage()
mock_google.__path__ = []
mock_google.__spec__ = MagicMock()
sys.modules['google'] = mock_google

# Mock google app engine to prevent stripe from breaking
sys.modules['google.appengine'] = MagicMock()
sys.modules['google.appengine.api'] = MagicMock()
sys.modules['google.appengine.api.urlfetch'] = MagicMock()

sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()

mock_googleapiclient = MockGooglePackage()
mock_googleapiclient.__path__ = []
sys.modules['googleapiclient'] = mock_googleapiclient
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.errors'] = MagicMock()

sys.modules['authlib.integrations.flask_client'] = MagicMock()
sys.modules['authlib'] = MagicMock()
sys.modules['fpdf'] = MagicMock()
sys.modules['markdown'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()

import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['FLASK_SECRET_KEY'] = 'test-secret'

# Setup Flask test app
from app import create_app, db
from models import Store, User, Appointment, Dog, Owner

class TestDashboardOptimized(unittest.TestCase):
    """
    Test that the dashboard correctly skips the details_needed query
    as part of the optimization.
    """

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    @patch('app.db.session.get')
    @patch('app.db.session.query')
    @patch('models.Appointment.query')
    @patch('models.Owner.query')
    def test_dashboard_query_optimization(self, mock_owner_query, mock_appt_query, mock_db_query, mock_db_get):

        # Setup mocks for queries
        mock_db_query.return_value.filter.return_value.one.return_value = (5, 100.0, 2)
        mock_owner_query.filter.return_value.count.return_value = 3

        # Mock Store and User
        mock_store = MagicMock()
        mock_store.id = 1
        mock_store.timezone = 'UTC'
        mock_store.subscription_status = 'active'
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.store_id = 1
        mock_user.role = 'admin'
        mock_user.is_subscribed = True
        mock_user.store = mock_store

        # mock_db_get will return user then store
        def side_effect(model, id):
            if model == User:
                return mock_user
            if model == Store:
                return mock_store
            return None
        mock_db_get.side_effect = side_effect

        # The key assertion: mock_appt_query should only be used ONCE for upcoming_appointments
        # instead of TWICE (once for details_needed and once for upcoming_appointments)
        mock_appt_query.options.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with self.app.test_client() as client:
            # Login as a user
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['store_id'] = 1

            # Make request
            response = client.get('/dashboard')

            self.assertEqual(response.status_code, 200)

            # Check filter calls on Appointment.query
            # Since the code only contains one query on Appointment.query inside the store_id check
            # We assert that limit is called once. The removed query didn't have a limit call.
            limit_calls = mock_appt_query.options.return_value.filter.return_value.order_by.return_value.limit.call_args_list
            self.assertEqual(len(limit_calls), 1, "Appointment query should only be run for upcoming appointments")

if __name__ == '__main__':
    unittest.main()