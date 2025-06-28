# input_sanitization.py
"""
Central utilities for input sanitization and XSS protection.
Use `sanitize_text_input` for any user-supplied text before saving to DB or rendering.
"""
import re
from markupsafe import escape

def sanitize_text_input(text):
    """
    Escapes HTML and strips dangerous tags from user input.
    Use for any free-text field from forms before storing or rendering.
    """
    if not text:
        return ''
    # Escape HTML
    text = escape(text)
    # Optionally strip dangerous tags (e.g. script/style)
    # Remove script/style blocks
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove event handlers (e.g. onclick)
    text = re.sub(r'on\w+\s*=\s*"[^"]*"', '', text, flags=re.IGNORECASE)
    text = re.sub(r'on\w+\s*=\s*\'[^\']*\'', '', text, flags=re.IGNORECASE)
    text = re.sub(r'on\w+\s*=\s*[^\s>]+', '', text, flags=re.IGNORECASE)
    return text
