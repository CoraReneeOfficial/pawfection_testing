from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, current_app, jsonify
from models import User, ActivityLog, Store
from extensions import db
from functools import wraps
import datetime
from datetime import timezone
from sqlalchemy.exc import IntegrityError
from utils import allowed_file # Keep allowed_file from utils
from utils import log_activity   # IMPORT log_activity from utils.py
import os
from authlib.integrations.flask_client import OAuth
import base64
import json

auth_bp = Blueprint('auth', __name__)

# Set up OAuth
oauth = OAuth()
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/gmail.send'},
)

def check_initial_setup():
    """
    Checks if any user exists in the database.
    This is used to determine if the initial admin setup needs to be performed.
    """
    return User.query.first() is None

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles user login.
    Users log in within the context of a previously selected store.
    """
    from flask_login import logout_user
    logout_user()  # Force logout to require login every time
    session.pop('user_id', None)  # Only clear user_id, not store_id
    # Do NOT clear session['store_id'] here!
    # If no users exist, redirect to initial setup
    if check_initial_setup():
        flash("Please complete initial setup.", "warning")
        return redirect(url_for('auth.initial_setup'))
    
    # If a user is already logged in, redirect to dashboard
    if getattr(g, 'user', None):
        return redirect(url_for('dashboard'))
    
    # Ensure a store is selected in the session
    store_id = session.get('store_id')
    store_name = None
    if not store_id:
        flash("Please select your store first.", "warning")
        return redirect(url_for('store_login')) # Redirect to store selection if no store_id
    
    # Fetch store details for display purposes
    store = db.session.get(Store, store_id)
    if store:
        store_name = store.name
    else:
        # If store_id is in session but store not found, clear session and redirect
        flash("Selected store not found. Please select your store again.", "danger")
        session.pop('store_id', None)
        return redirect(url_for('store_login'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash("Username and password required.", "danger")
            return render_template('login.html', show_initial_setup=check_initial_setup(), store_name=store_name), 400
        
        # --- DEBUG LOGGING ---
        current_app.logger.info(f"[LOGIN DEBUG] Attempt login: username={username}, store_id={store_id}, password_entered={password}")
        # Authenticate user within the context of the current store
        user = User.query.filter_by(username=username, store_id=store_id).first()
        if user:
            current_app.logger.info(f"[LOGIN DEBUG] Found user: {user.username}, id={user.id}, store_id={user.store_id}")
        else:
            current_app.logger.info(f"[LOGIN DEBUG] No user found for username={username}, store_id={store_id}")
        # --- END DEBUG LOGGING ---
        
        pw_check = user.check_password(password) if user else False
        current_app.logger.info(f"[LOGIN DEBUG] Password check passed: {pw_check}")
        
        if user and pw_check:
            session.clear() # Clear any existing session data (important for security)
            # Now log in the user (this sets the Flask-Login session cookie)
            from flask_login import login_user
            login_user(user)
            # Set any extra session variables you need
            session['user_id'] = user.id
            session['store_id'] = store_id  # Re-establish store context in the new session
            session.permanent = True # Make the session persistent
            g.user = user # Set the global user object
            
            log_activity("Logged in") # Log the login activity
            flash(f"Welcome back, {user.username}!", "success")
            
            # Redirect to 'next' page if provided and safe, otherwise to dashboard
            next_page = request.args.get('next')
            if next_page and not (next_page.startswith('/') or next_page.startswith(request.host_url)):
                current_app.logger.warning(f"Invalid 'next' URL: {next_page}")
                next_page = None
            return redirect(next_page or url_for('dashboard'))
        else:
            flash("Invalid username or password.", "danger")
            return render_template('login.html', show_initial_setup=check_initial_setup(), store_name=store_name), 401
    
    return render_template('login.html', show_initial_setup=check_initial_setup(), store_name=store_name)

@auth_bp.route('/logout')
def logout():
    """
    Handles user logout.
    Clears the user session and redirects to the login page.
    """
    # Log activity before clearing session, as g.user will be gone afterwards
    log_activity("Logged out") 
    session.pop('user_id', None)
    # Note: We keep 'store_id' in session on logout so user doesn't have to re-select store
    g.user = None # Clear global user object
    flash("Logged out successfully.", "info")
    return redirect(url_for('auth.login'))

@auth_bp.route('/initial_setup', methods=['GET', 'POST'])
def initial_setup():
    """
    Handles the initial setup of the application, creating the first admin user.
    This route is only accessible if no users exist in the database.
    """
    if not check_initial_setup():
        flash("Initial setup already completed.", "info")
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        errors = False
        if not username:
            flash("Username required.", "danger")
            errors = True
        if not password:
            flash("Password required.", "danger")
            errors = True
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            errors = True
        if len(password) < 8 and password:
            flash("Password too short (min 8 chars).", "danger")
            errors = True
        
        if errors:
            return render_template('initial_setup.html'), 400
        
        # For initial setup, this user is a global superadmin, not tied to a specific store.
        # Their store_id should be None.
        admin_user = User(username=username, is_admin=True, is_groomer=True, role='superadmin', store_id=None)
        admin_user.set_password(password)
        
        try:
            db.session.add(admin_user)
            db.session.commit()
            
            # Log the activity for initial setup
            created_user = User.query.filter_by(username=username).first()
            if created_user:
                # For initial setup, the store_id for this activity log will be None
                # as it's a global superadmin creation.
                log_activity("Initial admin account created", details=f"Username: {username}")
                
            flash("Admin account created! Please log in.", "success")
            return redirect(url_for('auth.login'))
        
        except IntegrityError:
            db.session.rollback()
            flash("Username taken (IntegrityError).", "danger")
            current_app.logger.error("IntegrityError during initial_setup.")
            return render_template('initial_setup.html'), 500
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error initial setup: {e}", exc_info=True)
            flash("Error during setup.", "danger")
            return render_template('initial_setup.html'), 500
    
    return render_template('initial_setup.html')

@auth_bp.route('/google/authorize')
def google_authorize():
    redirect_uri = url_for('auth.google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@auth_bp.route('/google/callback')
def google_callback():
    token = google.authorize_access_token()
    userinfo = token.get('userinfo')
    if not userinfo:
        flash('Failed to get user info from Google.', 'danger')
        return redirect(url_for('auth.login'))

    # Try to find user by Google sub (unique ID)
    user = User.query.filter_by(google_sub=userinfo['sub']).first()
    if not user:
        # Optionally, also check by email if you want to link existing accounts
        user = User.query.filter_by(email=userinfo['email']).first()
        if user:
            # Link Google account to existing user
            user.google_sub = userinfo['sub']
            db.session.commit()
        else:
            flash('No account found for this Google user. Please contact your administrator.', 'danger')
            return redirect(url_for('auth.login'))

    # Log the user in
    session.clear()
    session['user_id'] = user.id
    session.permanent = True
    g.user = user

    flash(f"Logged in as {userinfo['email']}", 'success')
    return redirect(url_for('dashboard'))

@auth_bp.route('/google/debug-redirect-uri')
def google_debug_redirect_uri():
    return jsonify({
        'google_callback_url': url_for('auth.google_callback', _external=True)
    })

def admin_required_for_store(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = g.user
        store_id = kwargs.get('store_id') or session.get('store_id')
        if not user or not user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        # Optionally, check if user is admin for the specific store
        # if user.role == 'superadmin' or (user.is_admin and user.store_id == store_id):
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/store/connect_google')
@admin_required_for_store
def connect_google():
    store_id = request.args.get('store_id') or session.get('store_id')
    if not store_id:
        flash('No store selected.', 'danger')
        return redirect(url_for('management.management'))
    session['google_oauth_store_id'] = int(store_id)
    redirect_uri = url_for('auth.google_store_callback', _external=True)
    # Explicitly request refresh token and consent
    return google.authorize_redirect(
        redirect_uri,
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true'
    )

@auth_bp.route('/google/store_callback')
@admin_required_for_store
def google_store_callback():
    store_id = session.pop('google_oauth_store_id', None)
    if not store_id:
        flash('No store selected for Google connection.', 'danger')
        return redirect(url_for('management.management'))
    token = google.authorize_access_token()
    if not token:
        flash('Failed to connect Google account.', 'danger')
        return redirect(url_for('management.management'))
    store = Store.query.get(store_id)
    if not store:
        flash('Store not found.', 'danger')
        return redirect(url_for('management.management'))
    # Extract and save only the required fields
    token_data = {
        'token': token.get('access_token') or token.get('token'),
        'refresh_token': token.get('refresh_token'),
        'token_uri': token.get('token_uri', 'https://oauth2.googleapis.com/token'),
        'client_id': token.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
        'client_secret': token.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
        'scopes': token.get('scopes') if 'scopes' in token else token.get('scope', '').split()
    }
    # Check for required fields
    missing_fields = [k for k in ['token', 'refresh_token', 'token_uri', 'client_id', 'client_secret'] if not token_data.get(k)]
    if missing_fields:
        current_app.logger.error(f"[Google OAuth] Missing required fields in token: {missing_fields}")
        flash('Failed to retrieve all required credentials from Google. Please try reconnecting and ensure you grant all requested permissions.', 'danger')
        return redirect(url_for('management.management'))
    store.google_token_json = json.dumps(token_data)
    db.session.commit()

    # --- Google Calendar: Find or create 'Pawfection Appointments' calendar ---
    try:
        from google.oauth2.credentials import Credentials as GoogleCredentials
        from googleapiclient.discovery import build
        import json as _json
        token_data = _json.loads(store.google_token_json)
        creds = GoogleCredentials(
            token=token_data.get('access_token') or token_data.get('token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_data.get('client_id'),
            client_secret=token_data.get('client_secret'),
            scopes=token_data.get('scopes') if 'scopes' in token_data else token_data.get('scope', '').split()
        )
        service = build('calendar', 'v3', credentials=creds)
        # List calendars
        calendar_list = service.calendarList().list().execute()
        pawfection_calendar = None
        for cal in calendar_list.get('items', []):
            if cal.get('summary') == 'Pawfection Appointments':
                pawfection_calendar = cal
                break
        if not pawfection_calendar:
            # Create the calendar
            calendar = {
                'summary': 'Pawfection Appointments',
                'timeZone': store.timezone or 'UTC',
            }
            pawfection_calendar = service.calendars().insert(body=calendar).execute()
        # Save the calendar ID
        store.google_calendar_id = pawfection_calendar['id']
        db.session.commit()
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        current_app.logger.error(f"[Google Calendar] Failed to find/create calendar: {e}\nTraceback:\n{tb}")
        flash('Google account connected, but failed to set up the calendar. Please check your Google account permissions.', 'warning')

    flash('Google account connected successfully!', 'success')
    return redirect(url_for('management.management'))
