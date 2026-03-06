import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Mock troublesome modules before importing app
mock_bcrypt = MagicMock()
mock_bcrypt.gensalt.return_value = b'$2b$12$...'
mock_bcrypt.hashpw.return_value = b'$2b$12$hashedpassword'
mock_bcrypt.checkpw.return_value = True
sys.modules['bcrypt'] = mock_bcrypt

sys.modules['psutil'] = MagicMock()
sys.modules['stripe'] = MagicMock()
sys.modules['authlib'] = MagicMock()
sys.modules['authlib.integrations.flask_client'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['google.genai'] = MagicMock()
sys.modules['google_auth_oauthlib'] = MagicMock()
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['googleapiclient'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.errors'] = MagicMock()
sys.modules['apscheduler'] = MagicMock()
sys.modules['apscheduler.schedulers.background'] = MagicMock()
sys.modules['fpdf'] = MagicMock()
sys.modules['pandas'] = MagicMock()
sys.modules['xlsxwriter'] = MagicMock()
sys.modules['ollama'] = MagicMock()
sys.modules['markdown'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()

# Mocking Flask-Mail as it might be imported
sys.modules['flask_mail'] = MagicMock()

from app import create_app, db
from models import User

class TestBackupPathTraversal(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            if not User.query.filter_by(username='admin').first():
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
            with self.app.app_context():
                user = User.query.filter_by(username='admin').first()
                if user:
                    sess['user_id'] = user.id
                    sess['is_superadmin'] = True
                    sess['_fresh'] = True

    def test_download_path_traversal_simple(self):
        self.login()
        # Attempt path traversal with ..
        response = self.client.get('/superadmin/backup/download/../../app.py')
        self.assertEqual(response.status_code, 404)

    def test_download_path_traversal_complex(self):
        self.login()
        # Attempt path traversal with malicious prefix but containing ..
        response = self.client.get('/superadmin/backup/download/db_backup_../../../etc/passwd.sqlite')
        self.assertEqual(response.status_code, 404)

    def test_delete_path_traversal(self):
        self.login()
        # Attempt path traversal on delete route
        response = self.client.post('/superadmin/backup/delete/../../app.py')
        self.assertEqual(response.status_code, 404)

    @patch('flask.send_from_directory')
    @patch('os.path.exists')
    def test_download_legitimate_file(self, mock_exists, mock_send):
        self.login()
        mock_exists.return_value = True

        filename = "db_backup_20230101_120000.sqlite"
        mock_send.return_value = "file content"
        response = self.client.get(f'/superadmin/backup/download/{filename}')
        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()

if __name__ == '__main__':
    unittest.main()
