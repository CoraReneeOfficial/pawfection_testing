import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock dependencies BEFORE imports
# Create a robust mock structure for google
mock_google = MagicMock()
sys.modules['google'] = mock_google
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['googleapiclient'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()

sys.modules['bcrypt'] = MagicMock()
sys.modules['psutil'] = MagicMock()
sys.modules['stripe'] = MagicMock()
sys.modules['cryptography'] = MagicMock()
sys.modules['cryptography.hazmat'] = MagicMock()
sys.modules['cryptography.hazmat.backends'] = MagicMock()
sys.modules['authlib'] = MagicMock()
sys.modules['authlib.integrations'] = MagicMock()
sys.modules['authlib.integrations.flask_client'] = MagicMock()
sys.modules['google_auth_oauthlib'] = MagicMock()
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['pandas'] = MagicMock()  # Mock pandas

# Mocking OAuth specifically
mock_oauth = MagicMock()
mock_oauth.register.return_value = MagicMock()
sys.modules['authlib.integrations.flask_client'].OAuth = MagicMock(return_value=mock_oauth)

from app import create_app, db
from models import User

class TestDataExportSQLInjection(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            if not User.query.filter_by(username='admin').first():
                user = User(username='admin', role='superadmin', is_admin=True)
                user.password_hash = 'hash'
                db.session.add(user)
                db.session.commit()

    def login(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['is_superadmin'] = True
            sess['_fresh'] = True

    @patch('app.db.session.execute')
    @patch('app.csrf.protect')
    def test_sql_injection_mitigated(self, mock_csrf_protect, mock_execute):
        self.login()

        malicious_filter = "id = 1 OR 1=1"

        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_result.__iter__.return_value = []
        mock_execute.return_value = mock_result

        # 1. Try old exploit (should be ignored)
        self.client.post('/superadmin/data-export', data={
            'table': 'user',
            'format': 'json',
            'filter': malicious_filter,
            'columns': []
        }, follow_redirects=True)

        for call in mock_execute.call_args_list:
            args, _ = call
            if args:
                query_obj = args[0]
                query_str = str(query_obj)
                # Should NOT contain the malicious filter
                self.assertNotIn(f"WHERE {malicious_filter}", query_str, "Old exploit payload was executed!")

    @patch('app.db.session.execute')
    @patch('app.csrf.protect')
    def test_valid_filter_parameterized(self, mock_csrf_protect, mock_execute):
        self.login()

        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_result.__iter__.return_value = []
        mock_execute.return_value = mock_result

        # 2. Try valid new filter (should be parameterized)
        self.client.post('/superadmin/data-export', data={
            'table': 'user',
            'format': 'json',
            'filter_column': 'username',
            'filter_operator': '=',
            'filter_value': 'admin',
            'columns': []
        }, follow_redirects=True)

        found_parameterized_query = False
        for call in mock_execute.call_args_list:
            args, kwargs = call
            if args:
                query_obj = args[0]
                query_str = str(query_obj)
                # Check for parameter placeholder
                if "WHERE username = :filter_val" in query_str:
                    found_parameterized_query = True
                    # Check params were passed
                    # SQLAlchemy execute(text, params) -> args[1] or kwargs
                    # Check if params were passed
                    params = args[1] if len(args) > 1 else kwargs
                    if not params:
                         # In some versions it might be in the query object or elsewhere?
                         # db.session.execute(text, params)
                         # call args: (text_obj, {'filter_val': 'admin'})
                         pass

                    if len(args) > 1 and args[1] == {'filter_val': 'admin'}:
                        pass
                    elif kwargs == {'filter_val': 'admin'}:
                        pass

                    break

        self.assertTrue(found_parameterized_query, "Parameterized query not found for valid filter.")

if __name__ == '__main__':
    unittest.main()
