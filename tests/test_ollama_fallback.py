import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Mock sys.modules for dotenv to avoid database errors
sys.modules['dotenv'] = MagicMock()
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['GEMINI_API_KEY'] = 'test-key'
os.environ['ENABLE_AI_ASSISTANT'] = 'True'

# Mock google.genai and ollama before importing app
google_mock = MagicMock()
google_mock.__path__ = [] # make it a package
sys.modules['google'] = google_mock
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()

google_oauth2_mock = MagicMock()
google_oauth2_mock.__path__ = []
sys.modules['google.oauth2'] = google_oauth2_mock
sys.modules['google.oauth2.credentials'] = MagicMock()

google_auth_mock = MagicMock()
google_auth_mock.__path__ = []
sys.modules['google.auth'] = google_auth_mock
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()

google_api_client_mock = MagicMock()
google_api_client_mock.__path__ = []
sys.modules['googleapiclient'] = google_api_client_mock
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.errors'] = MagicMock()

sys.modules['ollama'] = MagicMock()

# Mock bcrypt completely but give it what it needs
bcrypt_mock = MagicMock()
bcrypt_mock.hashpw.return_value = b'hashed_password'
bcrypt_mock.gensalt.return_value = b'salt'
bcrypt_mock.checkpw.return_value = True
sys.modules['bcrypt'] = bcrypt_mock

sys.modules['psycopg2'] = MagicMock()
sys.modules['fpdf'] = MagicMock()
sys.modules['markdown'] = MagicMock()
sys.modules['markdown'].markdown.return_value = "<html>Mock HTML</html>"
sys.modules['cryptography'] = MagicMock()

# proper authlib mock package
authlib_mock = MagicMock()
sys.modules['authlib'] = authlib_mock
sys.modules['authlib.integrations'] = authlib_mock
sys.modules['authlib.integrations.flask_client'] = authlib_mock

sys.modules['stripe'] = MagicMock()

from app import create_app
from extensions import db
from models import User, Store

class TestOllamaFallback(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create a test store and user
            self.store = Store(name="Test Store", username="test_store", password_hash="hash")
            db.session.add(self.store)
            db.session.commit()

            self.store_id = self.store.id

            self.user = User(username='test_user', email='test@test.com', store_id=self.store.id, is_groomer=True)
            self.user.set_password("pass")
            db.session.add(self.user)
            db.session.commit()

            self.user_id = self.user.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    @patch('ai_assistant.routes.ollama')
    @patch('ai_assistant.routes.genai')
    def test_ollama_fallback_to_gemini(self, mock_genai, mock_ollama):
        # Mock ollama to raise an exception
        mock_ollama_client = MagicMock()
        mock_ollama_client.chat.side_effect = Exception("Connection refused")
        mock_ollama.Client.return_value = mock_ollama_client

        # Mock gemini to return a valid response
        mock_gemini_client = MagicMock()
        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello from Gemini"
        mock_chat.send_message.return_value = mock_response
        mock_gemini_client.chats.create.return_value = mock_chat
        mock_genai.Client.return_value = mock_gemini_client

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['store_id'] = self.store_id

        response = self.client.post('/ai/chat', json={'message': 'hello'})

        self.assertEqual(response.status_code, 200)

        # Mock markdown is used to convert response_text, so the json response will just be whatever MagicMock returns, but we can verify the API called
        mock_ollama.Client.assert_called_once()
        mock_genai.Client.assert_called_once()

if __name__ == '__main__':
    unittest.main()
