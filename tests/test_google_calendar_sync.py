import unittest
from unittest.mock import MagicMock, patch
import sys
import json
import importlib

class TestGetGoogleCredentials(unittest.TestCase):
    def setUp(self):
        # Create mocks for dependencies
        self.mock_flask = MagicMock()
        self.mock_extensions = MagicMock()
        self.mock_models = MagicMock()
        self.mock_google = MagicMock()
        self.mock_google_oauth2 = MagicMock()
        self.mock_google_oauth2_credentials = MagicMock()
        self.mock_google_auth_transport_requests = MagicMock()
        self.mock_googleapiclient = MagicMock()
        self.mock_googleapiclient_discovery = MagicMock()
        self.mock_googleapiclient_errors = MagicMock()

        # Dictionary of modules to patch
        self.modules_to_patch = {
            'flask': self.mock_flask,
            'extensions': self.mock_extensions,
            'models': self.mock_models,
            'google': self.mock_google,
            'google.oauth2': self.mock_google_oauth2,
            'google.oauth2.credentials': self.mock_google_oauth2_credentials,
            'google.auth.transport.requests': self.mock_google_auth_transport_requests,
            'googleapiclient': self.mock_googleapiclient,
            'googleapiclient.discovery': self.mock_googleapiclient_discovery,
            'googleapiclient.errors': self.mock_googleapiclient_errors,
        }

        # Start patcher
        self.module_patcher = patch.dict(sys.modules, self.modules_to_patch)
        self.module_patcher.start()

        # Import module under test
        # We need to import inside the patched context.
        # Use importlib to ensure we get a fresh version if it was already imported.
        try:
            if 'appointments.google_calendar_sync' in sys.modules:
                import appointments.google_calendar_sync
                importlib.reload(appointments.google_calendar_sync)
                self.gcal_sync = appointments.google_calendar_sync
            else:
                import appointments.google_calendar_sync
                self.gcal_sync = appointments.google_calendar_sync
        except ImportError:
            # Fallback
            import appointments.google_calendar_sync
            self.gcal_sync = appointments.google_calendar_sync

        # Common setup
        self.store = MagicMock()
        self.store.id = 1

        # Valid token data
        self.valid_token_data = {
            'refresh_token': 'refresh_123',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'client_id': 'client_123',
            'client_secret': 'secret_123',
            'token': 'access_123'
        }
        self.store.google_token_json = json.dumps(self.valid_token_data)

    def tearDown(self):
        self.module_patcher.stop()

    def test_no_store(self):
        """Test with None store."""
        result = self.gcal_sync.get_google_credentials(None)
        self.assertIsNone(result)
        self.mock_flask.current_app.logger.error.assert_called_with("[GCAL SYNC] No Google token data available for store unknown")

    def test_no_token_json(self):
        """Test with store missing google_token_json."""
        self.store.google_token_json = None
        result = self.gcal_sync.get_google_credentials(self.store)
        self.assertIsNone(result)
        self.mock_flask.current_app.logger.error.assert_called_with(f"[GCAL SYNC] No Google token data available for store {self.store.id}")

    def test_invalid_json(self):
        """Test with invalid JSON in google_token_json."""
        self.store.google_token_json = "{invalid_json}"
        result = self.gcal_sync.get_google_credentials(self.store)
        self.assertIsNone(result)
        # Should catch JSONDecodeError and log error
        self.mock_flask.current_app.logger.error.assert_called()
        args, _ = self.mock_flask.current_app.logger.error.call_args
        self.assertIn("Error creating Google credentials", args[0])

    def test_missing_required_fields(self):
        """Test with JSON missing required fields."""
        incomplete_data = self.valid_token_data.copy()
        del incomplete_data['refresh_token']
        self.store.google_token_json = json.dumps(incomplete_data)

        result = self.gcal_sync.get_google_credentials(self.store)
        self.assertIsNone(result)
        self.mock_flask.current_app.logger.error.assert_called_with("[GCAL SYNC] Missing required token fields: refresh_token")

    def test_valid_credentials_not_expired(self):
        """Test with valid credentials that are not expired."""
        # Setup Credentials mock
        mock_creds_instance = MagicMock()
        mock_creds_instance.expired = False
        self.mock_google_oauth2_credentials.Credentials.return_value = mock_creds_instance

        result = self.gcal_sync.get_google_credentials(self.store)

        self.assertEqual(result, mock_creds_instance)
        self.mock_google_oauth2_credentials.Credentials.assert_called_once()
        _, kwargs = self.mock_google_oauth2_credentials.Credentials.call_args
        self.assertEqual(kwargs['token'], 'access_123')
        self.assertEqual(kwargs['refresh_token'], 'refresh_123')

    def test_expired_token_refresh_success(self):
        """Test with expired token that refreshes successfully."""
        # Setup Credentials mock
        mock_creds_instance = MagicMock()
        mock_creds_instance.expired = True

        # Configure refreshed credentials attributes
        mock_creds_instance.token = 'new_access_token'
        mock_creds_instance.refresh_token = 'new_refresh_token'
        mock_creds_instance.token_uri = 'https://oauth2.googleapis.com/token'
        mock_creds_instance.client_id = 'client_123'
        mock_creds_instance.client_secret = 'secret_123'
        mock_creds_instance.scopes = ['scope1']

        self.mock_google_oauth2_credentials.Credentials.return_value = mock_creds_instance

        result = self.gcal_sync.get_google_credentials(self.store)

        # Verify refresh was called
        mock_creds_instance.refresh.assert_called_once()
        self.assertTrue(self.mock_google_auth_transport_requests.Request.called)

        # Verify store was updated
        self.assertTrue(self.mock_extensions.db.session.add.called)
        self.assertTrue(self.mock_extensions.db.session.commit.called)

        # Verify new token data was saved to store
        saved_json = self.store.google_token_json
        saved_data = json.loads(saved_json)
        self.assertEqual(saved_data['token'], 'new_access_token')
        self.assertEqual(saved_data['refresh_token'], 'new_refresh_token')

        self.assertEqual(result, mock_creds_instance)

    def test_expired_token_refresh_failure(self):
        """Test with expired token where refresh fails."""
        # Setup Credentials mock
        mock_creds_instance = MagicMock()
        mock_creds_instance.expired = True
        mock_creds_instance.refresh.side_effect = Exception("Refresh failed")

        self.mock_google_oauth2_credentials.Credentials.return_value = mock_creds_instance

        result = self.gcal_sync.get_google_credentials(self.store)

        self.assertIsNone(result)
        self.mock_flask.current_app.logger.error.assert_called_with("[GCAL SYNC] Failed to refresh token: Refresh failed")

if __name__ == '__main__':
    unittest.main()
