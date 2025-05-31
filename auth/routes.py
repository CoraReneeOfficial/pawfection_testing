from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, current_app
from models import User, ActivityLog, Store
from extensions import db
from functools import wraps
import datetime
from datetime import timezone
from sqlalchemy.exc import IntegrityError
from utils import allowed_file # Keep allowed_file from utils
from utils import log_activity   # IMPORT log_activity from utils.py

auth_bp = Blueprint('auth', __name__)

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
    store = Store.query.get(store_id)
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
        
        # Authenticate user within the context of the current store
        user = User.query.filter_by(username=username, store_id=store_id).first()
        
        if user and user.check_password(password):
            session.clear() # Clear any existing session data (important for security)
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
