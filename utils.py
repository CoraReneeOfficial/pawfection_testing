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

def is_user_subscribed(user):
    """
    Returns True if the user's associated store has an active subscription (store.subscription_status == 'active'),
    or if the user is a superadmin (always allowed). Logs the check for debugging.
    """
    from flask import current_app
    if not user:
        current_app.logger.info('[SUBSCRIPTION] is_user_subscribed: No user object. Returning False.')
        print('[SUBSCRIPTION] is_user_subscribed: No user object. Returning False.')
        return False
    role = getattr(user, 'role', None)
    # Superadmin always has access
    if role == 'superadmin':
        current_app.logger.info(f"[SUBSCRIPTION] is_user_subscribed: user_id={getattr(user, 'id', None)}, username={getattr(user, 'username', None)}, role=superadmin -- ALWAYS ALLOWED")
        print(f"[SUBSCRIPTION] is_user_subscribed: user_id={getattr(user, 'id', None)}, username={getattr(user, 'username', None)}, role=superadmin -- ALWAYS ALLOWED")
        return True
    # Check store subscription status
    store = getattr(user, 'store', None)
    if not store:
        current_app.logger.info(f"[SUBSCRIPTION] is_user_subscribed: user_id={getattr(user, 'id', None)} has no associated store. DENIED.")
        print(f"[SUBSCRIPTION] is_user_subscribed: user_id={getattr(user, 'id', None)} has no associated store. DENIED.")
        return False
    status = getattr(store, 'subscription_status', None)
    allowed = status == 'active'
    current_app.logger.info(f"[SUBSCRIPTION] is_user_subscribed: user_id={getattr(user, 'id', None)}, store_id={getattr(store, 'id', None)}, subscription_status={status}, allowed={allowed}")
    print(f"[SUBSCRIPTION] is_user_subscribed: user_id={getattr(user, 'id', None)}, store_id={getattr(store, 'id', None)}, subscription_status={status}, allowed={allowed}")
    return allowed

from functools import wraps
from flask import g, flash, redirect, url_for

def subscription_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = getattr(g, 'user', None)
        current_app.logger.info(f"[SUBSCRIPTION] subscription_required: Checking access for user: {getattr(user, 'id', None)}, username={getattr(user, 'username', None)}, is_subscribed={getattr(user, 'is_subscribed', None)}")
        print(f"[SUBSCRIPTION] subscription_required: Checking access for user: {getattr(user, 'id', None)}, username={getattr(user, 'username', None)}, is_subscribed={getattr(user, 'is_subscribed', None)}")
        if not user or not is_user_subscribed(user):
            current_app.logger.info(f"[SUBSCRIPTION] subscription_required: DENIED for user: {getattr(user, 'id', None)}")
            print(f"[SUBSCRIPTION] subscription_required: DENIED for user: {getattr(user, 'id', None)}")
            flash('You need an active subscription to access this page.', 'warning')
            return redirect(url_for('subscribe'))
        current_app.logger.info(f"[SUBSCRIPTION] subscription_required: ALLOWED for user: {getattr(user, 'id', None)}")
        print(f"[SUBSCRIPTION] subscription_required: ALLOWED for user: {getattr(user, 'id', None)}")
        return f(*args, **kwargs)
    return decorated_function

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
            import time
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    db.session.add(log_entry)
                    db.session.commit()
                    break
                except Exception as e:
                    db.session.rollback()
                    if 'database is locked' in str(e).lower() and attempt < max_retries - 1:
                        current_app.logger.warning(f"[log_activity] Database is locked, retrying ({attempt+1}/{max_retries})...")
                        time.sleep(0.3)
                        continue
                    current_app.logger.error(f"Error logging activity: {e}", exc_info=True)
                    break
        except Exception as e:
            current_app.logger.error(f"Unexpected error in log_activity: {e}", exc_info=True)
    else:
        current_app.logger.warning(f"Attempted to log activity '{action}' but no user in g.")

def service_names_from_ids(service_ids_text):
    """Convert a comma-separated list of service IDs to a comma-separated list of service names."""
    if not service_ids_text:
        return ''

    # Import models here to avoid circular imports
    from models import Service

    # Split the comma-separated IDs
    service_ids = [int(sid) for sid in service_ids_text.split(',') if sid.strip().isdigit()]

    # If no valid IDs, return empty string
    if not service_ids:
        return ''

    # Get all services in one query
    services = Service.query.filter(Service.id.in_(service_ids)).all()

    # Map IDs to names
    id_to_name = {service.id: service.name for service in services}

    # Build names list in same order as IDs
    service_names = [id_to_name.get(sid, f"Unknown ({sid})") for sid in service_ids]

    # Join with commas
    return ', '.join(service_names)
