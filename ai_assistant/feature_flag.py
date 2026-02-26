import os

def is_ai_enabled():
    """
    Checks if the AI Assistant feature flag is enabled.
    Returns True if ENABLE_AI_ASSISTANT environment variable is set to 'True' (case-insensitive).
    """
    return os.environ.get('ENABLE_AI_ASSISTANT', 'False').lower() == 'true'
