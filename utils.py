import os
import datetime
from flask import g, session, current_app # Import current_app, g, session directly from flask
from extensions import db # Import db from extensions

# IMPORTANT: ActivityLog model is imported *inside* log_activity function
# to prevent potential circular imports if ActivityLog itself has dependencies that lead back to utils.
# This is a common pattern for breaking very complex circular dependencies.

def allowed_file(filename, allowed_extensions=None):
    """
    Checks if the filename has a valid extension.
    This function is used for file upload validation.
    """
    if allowed_extensions is None:
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def log_activity(action, details=None):
    """
    Logs user activity to the database, including the store context.
    This function uses Flask's application context (current_app, g, session)
    and imports the ActivityLog model locally to prevent circular imports.
    """
    # Import ActivityLog here, inside the function, to avoid top-level circular imports
    # if ActivityLog itself has dependencies that lead back here (e.g., if models.py imported utils).
    from models import ActivityLog 

    if hasattr(g, 'user') and g.user:
        try:
            # Retrieve store_id from the session.
            store_id = session.get('store_id') 
            
            log_entry = ActivityLog(
                user_id=g.user.id,
                action=action,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                details=details,
                store_id=store_id
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error logging activity: {e}", exc_info=True)
    else:
        current_app.logger.warning(f"Attempted to log activity '{action}' but no user in g.")

