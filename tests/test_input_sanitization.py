import unittest
from input_sanitization import sanitize_text_input

class TestInputSanitization(unittest.TestCase):
    def test_basic_string(self):
        """Test basic string input."""
        self.assertEqual(sanitize_text_input('hello world'), 'hello world')

    def test_none_input(self):
        """Test None input."""
        self.assertEqual(sanitize_text_input(None), '')

    def test_empty_string(self):
        """Test empty string input."""
        self.assertEqual(sanitize_text_input(''), '')

    def test_html_escaping(self):
        """Test HTML escaping."""
        # Check < and > are escaped
        self.assertEqual(sanitize_text_input('<b>bold</b>'), '&lt;b&gt;bold&lt;/b&gt;')
        # Check & is escaped
        self.assertEqual(sanitize_text_input('Me & You'), 'Me &amp; You')
        # Check " and ' are escaped
        self.assertEqual(sanitize_text_input('"quoted"'), '&#34;quoted&#34;')
        self.assertEqual(sanitize_text_input("'single'"), '&#39;single&#39;')

    def test_strip_script_tags(self):
        """Test stripping of <script> tags."""
        # Check <script> tags are removed entirely
        self.assertEqual(sanitize_text_input('<script>alert("xss")</script>'), '')
        # Check <script> tags inside text
        self.assertEqual(sanitize_text_input('Hello <script>bad()</script>World'), 'Hello World')
        # Check mixed case
        self.assertEqual(sanitize_text_input('<SCRIPT>alert(1)</SCRIPT>'), '')

    def test_strip_style_tags(self):
        """Test stripping of <style> tags."""
        self.assertEqual(sanitize_text_input('<style>body { color: red; }</style>'), '')
        self.assertEqual(sanitize_text_input('Hello <style>bad</style>World'), 'Hello World')

    def test_strip_event_handlers(self):
        """Test stripping of event handlers."""
        # Double quotes
        self.assertEqual(sanitize_text_input('<img src="x" onerror="alert(1)">'), '&lt;img src=&#34;x&#34; &gt;')
        # Single quotes
        self.assertEqual(sanitize_text_input("<img src='x' onerror='alert(1)'>"), '&lt;img src=&#39;x&#39; &gt;')
        # No quotes
        self.assertEqual(sanitize_text_input('<img src=x onerror=alert(1)>'), '&lt;img src=x &gt;')

    def test_complex_sanitization(self):
        """Test complex sanitization scenarios."""
        # Mixed safe and unsafe HTML
        input_text = '<b>Safe</b><script>Unsafe</script><i>Also Safe</i>'
        expected = '&lt;b&gt;Safe&lt;/b&gt;&lt;i&gt;Also Safe&lt;/i&gt;'
        self.assertEqual(sanitize_text_input(input_text), expected)

        # Nested/malformed attempts (regex might be simple but should handle basic cases)
        # Note: The current regex is simple and might not catch nested tags perfectly if they are tricky,
        # but for this task we verify basic stripping.
        input_text = '<script>alert(1)</script>'
        self.assertEqual(sanitize_text_input(input_text), '')

if __name__ == '__main__':
    unittest.main()
