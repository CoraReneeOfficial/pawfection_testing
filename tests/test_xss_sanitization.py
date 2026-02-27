import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import tempfile

# We need to set this BEFORE importing app to prevent it from trying to connect to a real DB
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

class TestXssSanitization(unittest.TestCase):
    def setUp(self):
        # --- Handle Environment & Dependencies ---
        self.original_sys_path = sys.path.copy()
        venv_site_packages = os.path.abspath("venv/Lib/site-packages")
        if os.path.exists(venv_site_packages) and venv_site_packages not in sys.path:
            sys.path.append(venv_site_packages)

        # Mocks
        self.mocks = {
            'bcrypt': MagicMock(),
            'authlib': MagicMock(),
            'authlib.integrations': MagicMock(),
            'authlib.integrations.flask_client': MagicMock(),
            'google': MagicMock(),
            'google.auth': MagicMock(),
            'google.auth.transport': MagicMock(),
            'google.auth.transport.requests': MagicMock(),
            'google.oauth2': MagicMock(),
            'google.oauth2.credentials': MagicMock(),
            'google_auth_oauthlib': MagicMock(),
            'google_auth_oauthlib.flow': MagicMock(),
            'googleapiclient': MagicMock(),
            'googleapiclient.discovery': MagicMock(),
            'googleapiclient.errors': MagicMock(),
            'cryptography': MagicMock(),
            'cryptography.hazmat': MagicMock(),
            'cryptography.hazmat.backends': MagicMock(),
            'cryptography.hazmat.primitives': MagicMock(),
            'cryptography.x509': MagicMock(),
            'fpdf': MagicMock(),
            'markdown': MagicMock(),
            'pandas': MagicMock(),
            'xlsxwriter': MagicMock(),
            'psutil': MagicMock(),
            'psycopg2': MagicMock(),
            'google.genai': MagicMock(),
        }
        self.mocks['google'].genai = self.mocks['google.genai']

        self.mocks['bcrypt'].gensalt.return_value = b'salt'
        self.mocks['bcrypt'].hashpw.side_effect = lambda pw, salt: pw + salt
        self.mocks['bcrypt'].checkpw.return_value = True

        self.modules_patcher = patch.dict(sys.modules, self.mocks)
        self.modules_patcher.start()

        self.migrate_patcher = patch('app.migrate_add_remind_at_to_notification')
        self.mock_migrate = self.migrate_patcher.start()
        self.stripe_patcher = patch('app.stripe')
        self.mock_stripe = self.stripe_patcher.start()

        # Mock dotenv
        self.dotenv_patcher = patch('app.load_dotenv')
        self.mock_dotenv = self.dotenv_patcher.start()

        # --- Initialize App Context ---
        from app import create_app, db
        from models import User, Store, Owner, Dog, Service

        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['WTF_CSRF_CHECK_DEFAULT'] = False
        self.app.config['SERVER_NAME'] = 'localhost.localdomain'

        # Mock csrf.protect globally for the app
        self.csrf_patcher = patch('extensions.csrf.protect')
        self.mock_csrf_protect = self.csrf_patcher.start()

        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        self.db = db
        self.User = User
        self.Store = Store
        self.Owner = Owner
        self.Dog = Dog
        self.Service = Service

        # Create a store and admin user
        self.store = Store(name='Test Store', username='storeuser', email='store@example.com')
        self.store.set_password('storepass')
        db.session.add(self.store)
        db.session.commit()

        self.user = User(username='testadmin', email='test@example.com', store_id=self.store.id, is_admin=True)
        self.user.set_password('password')
        db.session.add(self.user)
        db.session.commit()

        # Log in
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['store_id'] = self.store.id

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.app_context.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        self.migrate_patcher.stop()
        self.stripe_patcher.stop()
        self.dotenv_patcher.stop()
        self.csrf_patcher.stop()
        self.modules_patcher.stop()
        sys.path = self.original_sys_path

    def test_owner_input_sanitization(self):
        """Test if owner inputs are sanitized."""
        xss_payload = '<script>alert("XSS")</script>John Doe'

        # Add Owner
        response = self.client.post('/add_owner', data={
            'name': xss_payload,
            'phone': '555-1234',
            'email': 'john@example.com',
            'address': '123 Main St'
        }, follow_redirects=True)

        if response.status_code != 200:
             print(f"DEBUG: Add Owner Response Code: {response.status_code}")
             print(f"DEBUG: Add Owner Response: {response.data}")

        # Verify in DB
        owner = self.Owner.query.filter_by(phone_number='555-1234').first()

        if owner is None:
             self.fail("Owner creation failed")

        self.assertNotIn('<script>', owner.name)
        self.assertEqual(owner.name, 'John Doe') # Based on sanitize_text_input logic

    def test_dog_input_sanitization(self):
        """Test if dog inputs are sanitized."""
        owner = self.Owner(name='Jane Doe', phone_number='555-5678', store_id=self.store.id)
        self.db.session.add(owner)
        self.db.session.commit()

        xss_payload = '<script>alert("XSS")</script>Buddy'
        # The image tag will be stripped of event handlers and then escaped
        notes_payload = 'Loves treats <img src=x onerror=alert(1)>'

        # Add Dog
        response = self.client.post(f'/owner/{owner.id}/add_dog', data={
            'dog_name': xss_payload,
            'temperament': notes_payload
        }, follow_redirects=True)

        # Verify in DB
        dog = self.Dog.query.filter_by(owner_id=owner.id).first()

        if dog is None:
             print(f"DEBUG: Dog creation failed. Status: {response.status_code}")
             print(f"DEBUG: Response data: {response.data}")
             self.fail("Dog creation failed")

        # Verify sanitization
        self.assertNotIn('<script>', dog.name)
        self.assertEqual(dog.name, 'Buddy')

        self.assertNotIn('onerror', dog.temperament)
        self.assertNotIn('<img', dog.temperament) # Should be escaped to &lt;img

    def test_service_input_sanitization(self):
        """Test if service inputs are sanitized (Management)."""
        xss_payload = '<script>alert("XSS")</script>Service'

        response = self.client.post('/manage/services/add', data={
            'name': xss_payload,
            'base_price': '50.00',
            'item_type': 'service'
        }, follow_redirects=True)

        service = self.Service.query.filter_by(store_id=self.store.id).first()

        if service is None:
             self.fail("Service creation failed")

        # Verify sanitization
        self.assertNotIn('<script>', service.name)
        self.assertEqual(service.name, 'Service')

if __name__ == '__main__':
    unittest.main()
