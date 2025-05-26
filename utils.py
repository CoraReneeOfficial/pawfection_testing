import os
from flask import g, current_app, flash
from extensions import db
from models import ActivityLog

def allowed_file(filename, allowed_extensions=None):
    if allowed_extensions is None:
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions 

def log_activity(action, details=None):
    if hasattr(g, 'user') and g.user:
        try:
            log_entry = ActivityLog(user_id=g.user.id, action=action, details=details)
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error logging activity: {e}", exc_info=True)
    else:
        current_app.logger.warning(f"Attempted to log activity '{action}' but no user in g.") 