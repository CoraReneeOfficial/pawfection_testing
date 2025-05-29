import os
from flask import g, current_app, flash, session # These imports are kept for consistency with how utils.py often starts, though only 'os' is strictly needed for allowed_file.
from extensions import db # Kept for consistency, though not directly used by allowed_file.
# Removed 'from models import ActivityLog' as ActivityLog is no longer directly used here.
# Removed 'from auth import auth_bp' as it caused circular import and is not needed here.
import datetime # Kept for consistency, though not directly used by allowed_file.

def allowed_file(filename, allowed_extensions=None):
    """
    Checks if the filename has a valid extension.
    This function is used for file upload validation.
    """
    if allowed_extensions is None:
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

# IMPORTANT: The log_activity function has been moved to app.py to resolve circular import issues.
# It is no longer defined in utils.py.
# If you are looking for log_activity, please refer to your updated app.py file.
