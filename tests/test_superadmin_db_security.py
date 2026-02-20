import unittest
from unittest.mock import MagicMock
import sys

# Mock bcrypt before importing app
mock_bcrypt = MagicMock()
mock_bcrypt.gensalt.return_value = b'$2b$12$...'
mock_bcrypt.hashpw.return_value = b'$2b$12$hashedpassword'
mock_bcrypt.checkpw.return_value = True
sys.modules['bcrypt'] = mock_bcrypt

# Also mock other potential troublesome modules
sys.modules['psutil'] = MagicMock()
sys.modules['stripe'] = MagicMock()

from app import create_app, db
from models import User

class TestSuperadminDBSecurity(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False # Disable CSRF for testing
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            # Check if user already exists (create_app might create tables but not data)
            if not User.query.filter_by(username='admin').first():
                # Create superadmin directly in DB
                user = User(username='admin', role='superadmin', is_admin=True)
                user.password_hash = b'$2b$12$hashedpassword'
                db.session.add(user)
                db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self):
        with self.client.session_transaction() as sess:
            # Bypass login form and set session directly
            with self.app.app_context():
                user = User.query.filter_by(username='admin').first()
                if user:
                    sess['user_id'] = user.id
                    sess['is_superadmin'] = True
                    sess['_fresh'] = True

    def test_select_query_allowed(self):
        self.login()
        response = self.client.post('/superadmin/database', data={
            'action': 'run_query',
            'query': 'SELECT * FROM user'
        }, follow_redirects=True)
        # Check for success message or result table
        self.assertIn(b'Query executed successfully', response.data)

    def test_drop_table_blocked(self):
        self.login()
        response = self.client.post('/superadmin/database', data={
            'action': 'run_query',
            'query': 'DROP TABLE user'
        }, follow_redirects=True)
        # Should fail with security message
        self.assertIn(b'Only SELECT queries are allowed', response.data)

    def test_update_blocked(self):
        self.login()
        response = self.client.post('/superadmin/database', data={
            'action': 'run_query',
            'query': 'UPDATE user SET username="hacked"'
        }, follow_redirects=True)
        self.assertIn(b'Only SELECT queries are allowed', response.data)

    def test_semicolon_blocked(self):
        self.login()
        response = self.client.post('/superadmin/database', data={
            'action': 'run_query',
            'query': 'SELECT * FROM user; DROP TABLE user'
        }, follow_redirects=True)
        # Check for specific semicolon error or generic security error
        self.assertTrue(b'Multiple statements (semicolons) are not allowed' in response.data or b'Only SELECT queries are allowed' in response.data)

    def test_sql_comment_blocked(self):
        self.login()
        response = self.client.post('/superadmin/database', data={
            'action': 'run_query',
            'query': '-- SELECT\nDROP TABLE user'
        }, follow_redirects=True)
        # Comments are blocked
        self.assertTrue(b'SQL comments are not allowed' in response.data or b'Only SELECT queries are allowed' in response.data)

if __name__ == '__main__':
    unittest.main()
