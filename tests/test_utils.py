import unittest
from unittest.mock import MagicMock
import sys

# Mock modules to avoid dependencies
sys.modules['flask'] = MagicMock()
sys.modules['extensions'] = MagicMock()

# Import allowed_file from utils
from utils import allowed_file

class TestAllowedFile(unittest.TestCase):
    def test_default_allowed_extensions(self):
        """Test with default allowed extensions."""
        valid_extensions = ['png', 'jpg', 'jpeg', 'gif', 'webp']
        invalid_extensions = ['txt', 'exe', 'pdf', 'php', 'html']

        for ext in valid_extensions:
            self.assertTrue(allowed_file(f'image.{ext}'), f"Should allow {ext}")

        for ext in invalid_extensions:
            self.assertFalse(allowed_file(f'document.{ext}'), f"Should not allow {ext}")

    def test_case_insensitivity(self):
        """Test case insensitivity for extensions."""
        self.assertTrue(allowed_file('image.PNG'))
        self.assertTrue(allowed_file('image.Jpg'))
        self.assertTrue(allowed_file('image.PnG'))

    def test_custom_allowed_extensions(self):
        """Test with custom allowed extensions."""
        custom_extensions = {'pdf', 'docx'}
        self.assertTrue(allowed_file('document.pdf', custom_extensions))
        self.assertTrue(allowed_file('document.docx', custom_extensions))
        self.assertFalse(allowed_file('image.png', custom_extensions))

    def test_no_extension(self):
        """Test filenames with no extension."""
        self.assertFalse(allowed_file('image'))
        self.assertFalse(allowed_file('readme'))

    def test_multiple_dots(self):
        """Test filenames with multiple dots."""
        # Standard behavior: only the last part after the dot matters
        self.assertTrue(allowed_file('archive.tar.gz', {'gz'}))
        self.assertFalse(allowed_file('archive.tar.gz', {'tar'}))
        self.assertTrue(allowed_file('image.v1.png'))

    def test_empty_filename(self):
        """Test empty filename."""
        self.assertFalse(allowed_file(''))

    def test_dot_file(self):
        """Test filename with just a dot or starting with dot."""
        self.assertFalse(allowed_file('.'))
        # Hidden files like .gitignore -> extension is 'gitignore'
        self.assertTrue(allowed_file('.gitignore', {'gitignore'}))
        self.assertFalse(allowed_file('.gitignore', {'png'}))

    def test_path_traversal_check(self):
        """Test path traversal attempts."""
        # allowed_file doesn't check path traversal, just extension
        self.assertTrue(allowed_file('../../etc/passwd.png'))
        self.assertFalse(allowed_file('../../etc/passwd'))

if __name__ == '__main__':
    unittest.main()
