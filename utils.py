import os
from flask import g, current_app, flash, session  # Import session
from extensions import db
from models import ActivityLog

def allowed_file(filename, allowed_extensions=None):
    """
    Checks if the filename has a valid extension.
    """
    if allowed_extensions is None:
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions 

def log_activity(action, details=None):
    """
    Logs user activity to the database, including the store context.
    This function will now attempt to retrieve the store_id from the session
    and include it in the ActivityLog entry.
    """
    if hasattr(g, 'user') and g.user:
        try:
            # Retrieve store_id from the session. It's crucial that session['store_id']
            # is set correctly during store and user login.
            store_id = session.get('store_id') 
            
            log_entry = ActivityLog(
                user_id=g.user.id,
                action=action,
                details=details,
                store_id=store_id  # Assign the store_id to the log entry
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error logging activity: {e}", exc_info=True)
    else:
        current_app.logger.warning(f"Attempted to log activity '{action}' but no user in g.")
