import os
from flask import g, current_app, flash, session  # Import 'session' to access store_id
from extensions import db
from models import ActivityLog
import datetime  # Import the datetime module for timestamp handling

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
    This function has been enhanced with detailed logging to help diagnose store_id issues.
    """
    if hasattr(g, 'user') and g.user:
        try:
            # 1. Log the user and the action being performed.
            # This helps track which user is doing what.
            current_app.logger.debug(f"Logging activity: action='{action}', user_id={g.user.id}, username='{g.user.username}'")

            # 2. Retrieve the store_id from the session.
            # This is where we get the context of which store the user is currently working in.
            store_id = session.get('store_id')

            # 3. Log the value of store_id retrieved from the session.
            # This is the crucial debugging information you requested.
            current_app.logger.debug(f"session['store_id'] before log_activity: {store_id}")

            # 4. Check if store_id is None. If it is, log a WARNING.
            # This indicates a potential problem with session management.
            if store_id is None:
                current_app.logger.warning("store_id is None in log_activity!")

            # 5. Get the current UTC timestamp.
            # It's good practice to be explicit with timezones.
            timestamp = datetime.datetime.now(datetime.timezone.utc)
            current_app.logger.debug(f"Timestamp in log_activity: {timestamp}")

            # 6. Create the ActivityLog entry with all the necessary data.
            log_entry = ActivityLog(
                user_id=g.user.id,
                action=action,
                timestamp=timestamp,  # Use the explicitly created timestamp
                details=details,
                store_id=store_id      # Include the store_id
            )

            # 7. Add the entry to the database session and commit the changes.
            db.session.add(log_entry)
            db.session.commit()

            # 8. Log a success message.
            current_app.logger.debug("Activity logged successfully.")

        except Exception as e:
            # 9. If any error occurs, roll back the database transaction.
            # This prevents partial data from being saved.
            db.session.rollback()

            # 10. Log the error with detailed information (including traceback).
            current_app.logger.error(f"Error logging activity: {e}", exc_info=True)  # Include the traceback

    else:
        # 11. If there's no user in 'g', log a warning.
        # This should ideally never happen in a properly functioning application.
        current_app.logger.warning("Attempted to log activity but no user in g.")