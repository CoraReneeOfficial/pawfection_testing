import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to sys.path so we can import 'owners'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Mocking sys.modules to prevent real imports and side effects ---
MOCKED_MODULES = [
    'flask_sqlalchemy', 'flask_login', 'flask_migrate', 'flask_wtf',
    'flask_mail', 'google', 'google.oauth2', 'google_auth_oauthlib',
    'googleapiclient', 'authlib', 'authlib.integrations.flask_client',
    'apscheduler', 'apscheduler.schedulers.background', 'stripe',
    'secure_headers', 'flask', 'bcrypt', 'werkzeug', 'werkzeug.security',
    'sqlalchemy'
]

for module_name in MOCKED_MODULES:
    sys.modules[module_name] = MagicMock()

# Mock specific Flask components
mock_flask = MagicMock()
sys.modules['flask'] = mock_flask
mock_session = {}
mock_flask.session = mock_session
mock_flask.flash = MagicMock()
mock_flask.redirect = MagicMock()
mock_flask.url_for = MagicMock()
mock_flask.current_app = MagicMock()

# Configure Blueprint to pass-through decorators
def route_side_effect(*args, **kwargs):
    def decorator(f):
        return f
    return decorator

mock_blueprint_instance = MagicMock()
mock_blueprint_instance.route.side_effect = route_side_effect
mock_flask.Blueprint = MagicMock(return_value=mock_blueprint_instance)

mock_flask.render_template = MagicMock()
mock_flask.request = MagicMock()
mock_flask.g = MagicMock()

# Mock extensions
mock_db = MagicMock()
mock_extensions = MagicMock()
mock_extensions.db = mock_db
sys.modules['extensions'] = mock_extensions

# Mock models
mock_models = MagicMock()
sys.modules['models'] = mock_models

# Mock utils
mock_utils = MagicMock()
sys.modules['utils'] = mock_utils
mock_utils.log_activity = MagicMock()
# Mock allowed_file as well since it's imported
mock_utils.allowed_file = MagicMock()

# --- Import the function to test ---
from owners.routes import delete_owner

class TestOwnerDeleteLogic(unittest.TestCase):
    def setUp(self):
        # Reset mocks
        mock_flask.flash.reset_mock()
        mock_flask.redirect.reset_mock()
        mock_flask.url_for.reset_mock()
        mock_db.session.reset_mock()
        mock_models.Owner.query.reset_mock()
        mock_models.AppointmentRequest.query.reset_mock()
        mock_models.Receipt.query.reset_mock()
        mock_models.Appointment.query.reset_mock()
        mock_utils.log_activity.reset_mock()

        # Clear side effects
        mock_db.session.commit.side_effect = None

        # Setup session
        mock_flask.session['store_id'] = 1

    def test_delete_owner_success(self):
        """Test successful deletion of an owner."""
        # Setup Owner mock
        mock_owner = MagicMock()
        mock_owner.__bool__.return_value = True # Ensure it evaluates to True
        mock_owner.id = 101
        mock_owner.name = "John Doe"
        # Owner has dogs
        mock_dog = MagicMock()
        mock_dog.id = 201
        mock_owner.dogs = [mock_dog]

        # Setup Owner query to return this owner
        mock_models.Owner.query.filter_by.return_value.first.return_value = mock_owner

        # Setup AppointmentRequest query
        mock_req = MagicMock()
        mock_models.AppointmentRequest.query.filter_by.return_value.all.return_value = [mock_req]

        # Setup Appointment query (for dogs)
        mock_appt = MagicMock()
        mock_appt.id = 301
        mock_models.Appointment.query.filter.return_value.all.return_value = [mock_appt]

        # Call the function
        delete_owner(101)

        # Assertions
        # 1. Verify owner query
        mock_models.Owner.query.filter_by.assert_called_with(id=101, store_id=1)

        # 2. Verify AppointmentRequest unlink
        mock_models.AppointmentRequest.query.filter_by.assert_called_with(owner_id=101)
        self.assertIsNone(mock_req.owner_id)

        # 3. Verify Receipt deletion
        self.assertTrue(mock_models.Receipt.query.filter.return_value.delete.called)

        # 4. Verify Owner deletion
        mock_db.session.delete.assert_called_with(mock_owner)
        mock_db.session.commit.assert_called()

        # 5. Verify Logging and Flash
        mock_utils.log_activity.assert_called()
        mock_flask.flash.assert_called_with(
            'Owner "John Doe" and all their dogs/appointments have been deleted.',
            'success'
        )

        # 6. Verify Redirect
        mock_flask.redirect.assert_called()

    def test_delete_owner_not_found(self):
        """Test deletion when owner is not found or belongs to another store."""
        # Setup Owner query to return None
        mock_models.Owner.query.filter_by.return_value.first.return_value = None

        # Call the function
        delete_owner(999)

        # Assertions
        mock_db.session.delete.assert_not_called()
        mock_flask.flash.assert_called_with(
            'Owner not found or does not belong to this store.',
            'danger'
        )
        mock_flask.redirect.assert_called()

    def test_delete_owner_exception(self):
        """Test exception handling during deletion."""
        # Setup Owner mock
        mock_owner = MagicMock()
        mock_owner.__bool__.return_value = True
        mock_owner.id = 101
        mock_owner.name = "John Doe"
        mock_models.Owner.query.filter_by.return_value.first.return_value = mock_owner

        # Make db.session.commit raise an exception
        mock_db.session.commit.side_effect = Exception("Database error")

        # Call the function
        delete_owner(101)

        # Assertions
        mock_db.session.rollback.assert_called()
        mock_flask.flash.assert_called_with('Error deleting owner.', 'danger')
        mock_flask.current_app.logger.error.assert_called()

if __name__ == '__main__':
    unittest.main()
