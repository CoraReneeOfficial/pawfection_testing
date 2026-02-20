import unittest
from unittest.mock import MagicMock
from appointments.details_needed_utils import appointment_needs_details

class TestAppointmentDetails(unittest.TestCase):
    def setUp(self):
        # Create common mock objects
        self.mock_owner = MagicMock()
        self.mock_owner.name = "John Doe"

        self.mock_dog = MagicMock()
        self.mock_dog.owner = self.mock_owner
        self.mock_dog.name = "Buddy"

        self.mock_groomer = MagicMock()
        self.mock_groomer.username = "groomer1"

        self.services_text = "Full Grooming"

    def test_all_valid_returns_false(self):
        """Test that a fully detailed appointment returns False (no details needed)."""
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertFalse(result)

    def test_dog_none_returns_true(self):
        """Test that if dog is None, it returns True."""
        result = appointment_needs_details(None, self.mock_groomer, self.services_text)
        self.assertTrue(result)

    def test_dog_no_owner_returns_true(self):
        """Test that if dog has no owner, it returns True."""
        # Case 1: owner attribute is None
        self.mock_dog.owner = None
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertTrue(result)

        # Case 2: owner attribute is missing
        # Creating a mock without an 'owner' attribute using spec
        mock_dog_no_owner = MagicMock(spec=['name'])
        result = appointment_needs_details(mock_dog_no_owner, self.mock_groomer, self.services_text)
        self.assertTrue(result)

    def test_unknown_dog_name_returns_true(self):
        """Test that if dog name is 'Unknown Dog', it returns True."""
        self.mock_dog.name = "Unknown Dog"
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertTrue(result)

        # Test case insensitivity
        self.mock_dog.name = "unknown dog"
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertTrue(result)

        # Test with whitespace
        self.mock_dog.name = "  Unknown Dog  "
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertTrue(result)

    def test_unknown_owner_name_returns_true(self):
        """Test that if owner name is 'Unknown Owner', it returns True."""
        self.mock_owner.name = "Unknown Owner"
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertTrue(result)

        # Test case insensitivity
        self.mock_owner.name = "unknown owner"
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertTrue(result)

    def test_groomer_none_returns_true(self):
        """Test that if groomer is None, it returns True."""
        result = appointment_needs_details(self.mock_dog, None, self.services_text)
        self.assertTrue(result)

    def test_groomer_no_username_returns_true(self):
        """Test that if groomer has no username, it returns True."""
        self.mock_groomer.username = None
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertTrue(result)

        self.mock_groomer.username = ""
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertTrue(result)

        self.mock_groomer.username = "   "
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, self.services_text)
        self.assertTrue(result)

    def test_services_empty_returns_true(self):
        """Test that if services text is empty, it returns True."""
        result = appointment_needs_details(self.mock_dog, self.mock_groomer, None)
        self.assertTrue(result)

        result = appointment_needs_details(self.mock_dog, self.mock_groomer, "")
        self.assertTrue(result)

        result = appointment_needs_details(self.mock_dog, self.mock_groomer, "   ")
        self.assertTrue(result)

if __name__ == '__main__':
    unittest.main()
