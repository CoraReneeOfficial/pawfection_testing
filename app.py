# app.py
import os
import bcrypt
from flask import Flask, g, session, redirect, url_for, flash, send_from_directory, current_app
from flask.wrappers import Request
from extensions import db
from models import * # Import all models to ensure db.create_all() works correctly
from auth import auth_bp
from owners import owners_bp
from dogs import dogs_bp
from appointments import appointments_bp
from management import management_bp
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
from sqlalchemy.exc import IntegrityError # Import IntegrityError for database constraint errors
import datetime # Import datetime for timestamp handling in log_activity

# Configure basic logging for the application.
# This will output messages to the console (or wherever your environment directs stdout/stderr).
logging.basicConfig(level=logging.INFO) 

def create_app():
    """
    Creates and configures the Flask application instance.
    This function acts as the application factory.
    """
    app = Flask(__name__)

    # Define base directories for persistent data and uploads.
    # Uses environment variable 'PERSISTENT_DATA_DIR' if set, otherwise defaults to the app's base directory.
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    PERSISTENT_DATA_ROOT = os.environ.get('PERSISTENT_DATA_DIR', BASE_DIR)
    DATABASE_PATH = os.path.join(PERSISTENT_DATA_ROOT, 'grooming_business_v2.db')
    UPLOAD_FOLDER = os.path.join(PERSISTENT_DATA_ROOT, 'uploads')
    SHARED_TOKEN_FILE = os.path.join(PERSISTENT_DATA_ROOT, 'shared_google_token.json')
    NOTIFICATION_SETTINGS_FILE = os.path.join(PERSISTENT_DATA_ROOT, 'notification_settings.json')

    # Configure Flask application settings.
    # FLASK_SECRET_KEY is crucial for session security. Use a strong, random value in production.
    app.config['SECRET_KEY'] = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))
    
    # Configure SQLAlchemy to use PostgreSQL if DATABASE_URL is set, otherwise use SQLite.
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Disable Flask-SQLAlchemy event system for performance
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER # Folder for user-uploaded files (e.g., dog pictures)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # Max upload size (16 MB)
    app.config['SHARED_TOKEN_FILE'] = SHARED_TOKEN_FILE # Path for shared Google token (if applicable)
    app.config['NOTIFICATION_SETTINGS_FILE'] = NOTIFICATION_SETTINGS_FILE # Path for notification settings

    # Initialize Flask-SQLAlchemy with the app.
    db.init_app(app)

    # Route to serve uploaded files
    @app.route('/uploads/<path:filename>')
    def uploaded_persistent_file(filename):
        """
        Serves static files from the configured UPLOAD_FOLDER.
        This route allows web browsers to access uploaded images/files.
        """
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # Ensure all database tables are created on application startup.
    # In a production environment using Flask-Migrate, this line might be removed
    # as database schema management would be handled by migration commands.
    with app.app_context():
        db.create_all()

    # Define log_activity here to avoid circular import issues.
    # This function will be imported by other blueprints.
    def log_activity(action, details=None):
        """
        Logs user activity to the database, including the store context.
        This function is defined directly in app.py to avoid circular imports.
        It attempts to retrieve the store_id from the session and includes it in the ActivityLog entry.
        """
        if hasattr(g, 'user') and g.user:
            try:
                # Retrieve store_id from the session. It's crucial that session['store_id']
                # is set correctly during store and user login.
                store_id = session.get('store_id') 
                
                log_entry = ActivityLog(
                    user_id=g.user.id,
                    action=action,
                    timestamp=datetime.datetime.now(datetime.timezone.utc), # Use explicit UTC timestamp
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

    # Make log_activity available globally within the app context for blueprints to import
    # This is a common pattern for utility functions that depend on the app context.
    app.log_activity = log_activity


    # Register Flask Blueprints.
    # Blueprints modularize the application into smaller, reusable components.
    app.register_blueprint(auth_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(dogs_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(management_bp)

    # This function runs before every request to load the logged-in user.
    # It retrieves the user_id from the session and populates Flask's global 'g.user'.
    @app.before_request
    def load_logged_in_user():
        """
        Loads the logged-in user into Flask's global 'g' object before each request.
        This allows easy access to the current user's information throughout the app.
        Includes extensive logging for debugging user session loading and potential inconsistencies.
        """
        user_id = session.get('user_id')
        if user_id is None:
            g.user = None
            app.logger.debug("No user_id found in session. g.user set to None.")
        else:
            # Attempt to retrieve the User object from the database using the session's user_id.
            g.user = User.query.get(user_id)
            if g.user:
                # Log successful user loading, including their ID and associated store ID.
                app.logger.debug(f"Loaded user {g.user.username} (ID: {g.user.id}, Store ID: {g.user.store_id}) from session.")
            else:
                # If a user_id is in the session but no matching user is found in the DB,
                # it indicates an inconsistency. Log a warning and clear the invalid user_id from the session.
                app.logger.warning(f"User with ID {user_id} found in session but not in database. Clearing session user_id.")
                session.pop('user_id', None) # Remove the invalid user_id from the session
                g.user = None # Ensure g.user is None

    # Decorator to enforce login for specific routes.
    def login_required(view):
        """
        A decorator to ensure a user is logged in before accessing a route.
        If the user is not logged in, they are redirected to the login page with a flash message.
        """
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('auth.login'))
            return view(**kwargs)
        return wrapped_view

    # Add root route for the application's home page.
    @app.route('/')
    def home():
        from flask import render_template # Import render_template locally for this function
        return render_template('home_page.html')

    # Route for viewing the user agreement.
    @app.route('/user-agreement')
    def view_user_agreement():
        from flask import render_template # Import render_template locally
        return render_template('user_agreement.html')

    # Route for viewing the privacy policy.
    @app.route('/privacy-policy')
    def view_privacy_policy():
        from flask import render_template # Import render_template locally
        return render_template('privacy_policy.html')

    # Dashboard route, accessible only to logged-in users.
    @app.route('/dashboard')
    @login_required # Apply the login_required decorator
    def dashboard():
        from flask import render_template # Import render_template locally
        return render_template('dashboard.html')

    # Route for store login.
    # This is the initial login point for a store, setting the store context in the session.
    @app.route('/store/login', methods=['GET', 'POST'])
    def store_login():
        """
        Handles the login process for a specific store.
        Upon successful store authentication, the store's ID is stored in the session,
        establishing the context for subsequent user logins and data access.
        Includes logging for store login attempts (success and failure).
        """
        from flask import render_template, request # Import locally
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            # Attempt to find the store by username.
            store = Store.query.filter_by(username=username).first()
            if store and store.check_password(password):
                session['store_id'] = store.id # Set the store_id in the session
                # Log successful store login with store name and ID.
                app.logger.info(f"Store '{store.name}' (ID: {store.id}) logged in successfully. session['store_id'] set to {session['store_id']}.")
                flash(f"Store '{store.name}' logged in. Please sign in as a user.", "success")
                return redirect(url_for('auth.login')) # Redirect to user login after store selection
            else:
                # Log failed store login attempts.
                app.logger.warning(f"Invalid store username or password attempt for username: {username}.")
                flash('Invalid store username or password.', 'danger')
        return render_template('store_login.html')

    # Route for superadmin login.
    # Superadmins are global and not tied to a specific store.
    @app.route('/superadmin/login', methods=['GET', 'POST'])
    def superadmin_login():
        """
        Handles the login for the superadmin account.
        Superadmin accounts are designed to bypass store-specific filtering for administrative tasks.
        Upon successful login, the session is cleared, and superadmin status is set.
        """
        from flask import render_template, request # Import locally
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            # Authenticate superadmin: role='superadmin' and store_id=None (global user)
            user = User.query.filter_by(username=username, role='superadmin', store_id=None).first()
            if user and user.check_password(password):
                session.clear() # Clear any existing session data (e.g., store_id from a previous impersonation)
                session['user_id'] = user.id # Set the superadmin's user ID
                session['is_superadmin'] = True # Flag indicating superadmin session
                session.permanent = True # Make the session persistent
                app.logger.info(f"Superadmin '{user.username}' (ID: {user.id}) logged in.")
                flash(f"Superadmin '{user.username}' logged in.", "success")
                return redirect(url_for('dashboard')) # Redirect to dashboard
            else:
                app.logger.warning(f"Invalid superadmin username or password attempt for username: {username}.")
                flash('Invalid superadmin username or password.', 'danger')
        return render_template('superadmin_login.html')

    # Route for new store and initial admin user registration.
    @app.route('/store/register', methods=['GET', 'POST'])
    def store_register():
        """
        Handles the registration of a brand new grooming store and its first administrative user.
        Ensures uniqueness for store username and admin username.
        """
        from flask import render_template, request # Import locally
        if request.method == 'POST':
            store_name = request.form.get('store_name')
            store_username = request.form.get('store_username')
            store_password = request.form.get('store_password')
            admin_username = request.form.get('admin_username')
            admin_password = request.form.get('admin_password')
            
            errors = []
            # Basic validation for required fields
            if not store_name: errors.append('Store Name is required.')
            if not store_username: errors.append('Store Username is required.')
            if not store_password: errors.append('Store Password is required.')
            if not admin_username: errors.append('Admin Username is required.')
            if not admin_password: errors.append('Admin Password is required.')

            # Password length validation
            if len(store_password) < 8: errors.append('Store password must be at least 8 characters.')
            if len(admin_password) < 8: errors.append('Admin password must be at least 8 characters.')
            
            # Check for existing store username
            if Store.query.filter_by(username=store_username).first():
                errors.append('Store username already exists.')
            
            # Check if admin username exists globally (usernames are unique across all users)
            if User.query.filter_by(username=admin_username).first():
                errors.append('Admin username already exists. Please choose a different one.')
            
            # If any validation errors, re-render the form with messages
            if errors:
                for error in errors:
                    flash(error, 'danger')
                return render_template('store_register.html'), 400
            
            try:
                # Create the new store instance
                store = Store(name=store_name, username=store_username)
                store.set_password(store_password) # Hash and set store password
                db.session.add(store)
                db.session.flush() # Commit the store to get its ID before creating the user

                # Create the initial admin user for this new store
                admin_user = User(username=admin_username, role='admin', is_admin=True, is_groomer=True, store_id=store.id)
                admin_user.set_password(admin_password) # Hash and set admin password
                db.session.add(admin_user)
                db.session.commit() # Commit both store and admin user

                app.logger.info(f"New store '{store_name}' (ID: {store.id}) and admin user '{admin_username}' created successfully.")
                flash('Store and admin account created! Please log in to your store.', 'success')
                return redirect(url_for('store_login')) # Redirect to store login
            except IntegrityError:
                # Handle database integrity errors (e.g., duplicate unique fields)
                db.session.rollback() # Rollback transaction on error
                app.logger.error(f"IntegrityError during store registration for store {store_username} or admin {admin_username}.", exc_info=True)
                flash("A store or admin user with that name/username already exists. Please try different names.", "danger")
                return render_template('store_register.html'), 500
            except Exception as e:
                # Catch any other unexpected errors during registration
                db.session.rollback() # Rollback transaction
                app.logger.error(f"Error during store registration: {e}", exc_info=True)
                flash("An unexpected error occurred during registration.", "danger")
                return render_template('store_register.html'), 500
        return render_template('store_register.html')

    # Superadmin dashboard route.
    # Displays a list of all stores and their associated admin users.
    @app.route('/superadmin/dashboard')
    def superadmin_dashboard():
        """
        Displays the superadmin dashboard, providing an overview of all registered stores
        and their primary administrators. This route is exclusively accessible to superadmins.
        """
        from flask import render_template # Import locally
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        stores = Store.query.all() # Fetch all stores (superadmin view)
        # For each store, fetch its admin users.
        store_admins = {store.id: User.query.filter_by(store_id=store.id, is_admin=True).all() for store in stores}
        
        app.logger.info("Superadmin viewed dashboard.")
        return render_template('superadmin_dashboard.html', stores=stores, store_admins=store_admins)

    # Superadmin tools page route.
    @app.route('/superadmin/tools')
    def superadmin_tools():
        """
        Displays a page with various tools or options for the superadmin.
        Accessible only by superadmins.
        """
        from flask import render_template # Import locally
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        app.logger.info("Superadmin viewed tools page.")
        return render_template('superadmin_tools.html')

    # Superadmin impersonate store
    @app.route('/superadmin/impersonate/<int:store_id>')
    def superadmin_impersonate(store_id):
        """
        Allows a superadmin to 'impersonate' a specific store.
        This sets the session's 'store_id' to the target store's ID,
        allowing the superadmin to navigate the application as if they were a user of that store.
        """
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Verify that the target store actually exists before impersonating.
        store_to_impersonate = Store.query.get(store_id)
        if not store_to_impersonate:
            flash("Store not found for impersonation.", "danger")
            return redirect(url_for('superadmin_dashboard'))

        session['store_id'] = store_id # Set the store context in the session
        session['impersonating'] = True # Flag to indicate impersonation mode
        app.logger.info(f"Superadmin {g.user.username} (ID: {g.user.id}) is now impersonating store ID: {store_id} ('{store_to_impersonate.name}').")
        flash(f"Now impersonating store '{store_to_impersonate.name}'.", "info")
        return redirect(url_for('dashboard')) # Redirect to the main dashboard of the impersonated store

    # Superadmin stop impersonation
    @app.route('/superadmin/stop_impersonation')
    def superadmin_stop_impersonation():
        """
        Allows a superadmin to stop impersonating a store.
        This clears the 'store_id' and 'impersonating' flags from the session,
        reverting the superadmin to their global context.
        """
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        current_impersonated_store_id = session.get('store_id') # Log the store ID that was being impersonated
        session.pop('store_id', None) # Remove store context
        session.pop('impersonating', None) # Remove impersonation flag
        app.logger.info(f"Superadmin {g.user.username} (ID: {g.user.id}) stopped impersonating store ID: {current_impersonated_store_id}.")
        flash('Stopped impersonating store.', 'info')
        return redirect(url_for('superadmin_dashboard')) # Redirect back to superadmin dashboard

    # Apply ProxyFix middleware if the app is running behind a proxy server (e.g., Nginx, Gunicorn).
    # This helps Flask correctly determine the client's IP address and protocol.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    return app

if __name__ == '__main__':
    # This block runs the application when the script is executed directly.
    # debug=True enables debug mode, which provides a debugger and reloader.
    # Set FLASK_ENV=development in your environment for development mode.
    app = create_app()
    app.run(debug=True)
