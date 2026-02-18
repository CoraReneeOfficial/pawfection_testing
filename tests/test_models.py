import unittest
from unittest.mock import MagicMock
import sys

# List of modules to mock
MOCKED_MODULES = [
    'flask_sqlalchemy', 'flask_login', 'flask_migrate', 'flask_wtf',
    'flask_mail', 'google', 'google.oauth2', 'google_auth_oauthlib',
    'googleapiclient', 'authlib', 'authlib.integrations.flask_client',
    'apscheduler', 'apscheduler.schedulers.background', 'stripe',
    'secure_headers', 'flask', 'bcrypt'
]

# Create a generic mock for all dependencies
for module_name in MOCKED_MODULES:
    sys.modules[module_name] = MagicMock()

# Import bcrypt mock specifically for use in tests
import bcrypt as mock_bcrypt

# Special handling for extensions.db
mock_db = MagicMock()
mock_db.Model = object
import extensions
extensions.db = mock_db

# Now we can safely import User and Store from models
from models import User, Store

class TestModels(unittest.TestCase):
    def setUp(self):
        # Reset the bcrypt mock
        mock_bcrypt.reset_mock()
        # Default behavior for gensalt
        mock_bcrypt.gensalt.return_value = b'salt'
        # Default behavior for hashpw: return original + salt
        mock_bcrypt.hashpw.side_effect = lambda pw, salt: pw + salt

    def test_user_password_hashing(self):
        user = User()

        # Test setting password
        user.set_password('testpassword')
        mock_bcrypt.hashpw.assert_called_once_with('testpassword'.encode('utf-8'), b'salt')
        self.assertEqual(user.password_hash, 'testpasswordsalt')

        # Test checking password - correct
        mock_bcrypt.checkpw.return_value = True
        self.assertTrue(user.check_password('testpassword'))
        mock_bcrypt.checkpw.assert_called_with(
            'testpassword'.encode('utf-8'),
            'testpasswordsalt'.encode('utf-8')
        )

        # Test checking password - incorrect
        mock_bcrypt.checkpw.return_value = False
        self.assertFalse(user.check_password('wrongpassword'))

        # Test checking password - None (should raise AttributeError)
        with self.assertRaises(AttributeError):
            user.check_password(None)

    def test_store_password_hashing(self):
        store = Store()

        # Test setting password
        store.set_password('storepassword')
        self.assertEqual(store.password_hash, 'storepasswordsalt')

        # Test checking password - correct
        mock_bcrypt.checkpw.return_value = True
        self.assertTrue(store.check_password('storepassword'))

        # Test checking password - incorrect
        mock_bcrypt.checkpw.return_value = False
        self.assertFalse(store.check_password('wrongpassword'))

    def test_user_security_answer_verification(self):
        user = User()

        # Test setting security answer
        user.set_security_answer('My Answer')
        mock_bcrypt.hashpw.assert_called_with('my answer'.encode('utf-8'), b'salt')
        self.assertEqual(user.security_answer_hash, 'my answersalt')

        # Test checking security answer - correct (case-insensitive)
        mock_bcrypt.checkpw.return_value = True
        self.assertTrue(user.check_security_answer('MY ANSWER'))
        mock_bcrypt.checkpw.assert_called_with(
            'my answer'.encode('utf-8'),
            'my answersalt'.encode('utf-8')
        )

        # Test checking security answer - None or empty
        user.security_answer_hash = 'somehash'
        self.assertFalse(user.check_security_answer(None))
        self.assertFalse(user.check_security_answer(''))

    def test_store_security_answer_verification(self):
        store = Store()

        # Test setting security answer
        store.set_security_answer('Secret')

        # Test checking security answer - correct
        mock_bcrypt.checkpw.return_value = True
        self.assertTrue(store.check_security_answer('SECRET'))

        # Test checking security answer - missing hash
        store.security_answer_hash = None
        self.assertFalse(store.check_security_answer('SECRET'))

if __name__ == '__main__':
    unittest.main()
