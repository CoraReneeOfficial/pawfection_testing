# app.py
import os
import bcrypt
from flask import Flask, g, session, redirect, url_for, flash, send_from_directory, current_app
from flask.wrappers import Request
from extensions import db
from models import User, Store # Only import models directly needed in app.py's top level
from auth import auth_bp
from owners import owners_bp
from dogs import dogs_bp
from appointments import appointments_bp
from management import management_bp
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
from sqlalchemy.exc import IntegrityError
from utils import log_activity
# Removed import for datetime as it's not directly used at top level of app.py anymore
# Removed log_activity definition as it's now in utils.py

# Configure basic logging for the application.
logging.basicConfig(level=logging.INFO)

def create_app():
    """
    Creates and configures the Flask application instance.
    This function acts as the application factory.
    """
    app = Flask(__name__)

    # Define base directories for persistent data and uploads.
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    PERSISTENT_DATA_ROOT = os.environ.get('PERSISTENT_DATA_DIR', BASE_DIR)
    DATABASE_PATH = os.path.join(PERSISTENT_DATA_ROOT, 'grooming_business_v2.db')
    UPLOAD_FOLDER = os.path.join(PERSISTENT_DATA_ROOT, 'uploads')
    SHARED_TOKEN_FILE = os.path.join(PERSISTENT_DATA_ROOT, 'shared_google_token.json')
    NOTIFICATION_SETTINGS_FILE = os.path.join(PERSISTENT_DATA_ROOT, 'notification_settings.json')

    # Configure Flask application settings.
    app.config['SECRET_KEY'] = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))
    
    # Configure SQLAlchemy to use PostgreSQL if DATABASE_URL is set, otherwise use SQLite.
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    app.config['SHARED_TOKEN_FILE'] = SHARED_TOKEN_FILE
    app.config['NOTIFICATION_SETTINGS_FILE'] = NOTIFICATION_SETTINGS_FILE

    # Initialize Flask-SQLAlchemy with the app.
    db.init_app(app)

    # Initialize Flask-Migrate for database migrations
    from flask_migrate import Migrate
    migrate = Migrate(app, db)

    # Route to serve uploaded files
    @app.route('/uploads/<path:filename>')
    def uploaded_persistent_file(filename):
        """
        Serves static files from the configured UPLOAD_FOLDER.
        """
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # Ensure all database tables are created on application startup.
    with app.app_context():
        db.create_all()

    # Register Flask Blueprints.
    app.register_blueprint(auth_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(dogs_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(management_bp)

    # This function runs before every request to load the logged-in user.
    @app.before_request
    def load_logged_in_user():
        """
        Loads the logged-in user into Flask's global 'g' object before each request.
        """
        user_id = session.get('user_id')
        if user_id is None:
            g.user = None
            app.logger.debug("No user_id found in session. g.user set to None.")
        else:
            g.user = User.query.get(user_id)
            if g.user:
                app.logger.debug(f"Loaded user {g.user.username} (ID: {g.user.id}, Store ID: {g.user.store_id}) from session.")
            else:
                app.logger.warning(f"User with ID {user_id} found in session but not in database. Clearing session user_id.")
                session.pop('user_id', None)
                g.user = None

    # Decorator to enforce login for specific routes.
    def login_required(view):
        """
        A decorator to ensure a user is logged in before accessing a route.
        """
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('auth.login'))
            return view(**kwargs)
        return wrapped_view

    # Root route for the application's home page.
    @app.route('/')
    def home():
        from flask import render_template
        return render_template('home_page.html')

    # Legal pages routes
    @app.route('/user-agreement')
    def view_user_agreement():
        from flask import render_template
        return render_template('user_agreement.html')

    # Privacy policy route
    @app.route('/privacy-policy')
    def view_privacy_policy():
        from flask import render_template
        return render_template('privacy_policy.html')

    # Dashboard route
    @app.route('/dashboard')
    @login_required
    def dashboard():
        from flask import render_template
        return render_template('dashboard.html')

    # Store login route
    @app.route('/store/login', methods=['GET', 'POST'])
    def store_login():
        """
        Handles the login process for a specific store.
        """
        from flask import render_template, request
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            store = Store.query.filter_by(username=username).first()
            if store and store.check_password(password):
                session['store_id'] = store.id
                app.logger.info(f"Store '{store.name}' (ID: {store.id}) logged in successfully. session['store_id'] set to {session['store_id']}.")
                flash(f"Store '{store.name}' logged in. Please sign in as a user.", "success")
                return redirect(url_for('auth.login'))
            else:
                app.logger.warning(f"Invalid store username or password attempt for username: {username}.")
                flash('Invalid store username or password.', 'danger')
        return render_template('store_login.html')

    # Superadmin login route
    @app.route('/superadmin/login', methods=['GET', 'POST'])
    def superadmin_login():
        """
        Handles the login for the superadmin account.
        """
        from flask import render_template, request
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            user = User.query.filter_by(username=username, role='superadmin', store_id=None).first()
            if user and user.check_password(password):
                session.clear()
                session['user_id'] = user.id
                session['is_superadmin'] = True
                session.permanent = True
                app.logger.info(f"Superadmin '{user.username}' (ID: {user.id}) logged in.")
                flash(f"Superadmin '{user.username}' logged in.", "success")
                return redirect(url_for('dashboard'))
            else:
                app.logger.warning(f"Invalid superadmin username or password attempt for username: {username}.")
                flash('Invalid superadmin username or password.', 'danger')
        return render_template('superadmin_login.html')

    # Store registration route
    @app.route('/store/register', methods=['GET', 'POST'])
    def store_register():
        """
        Handles the registration of a new store and its initial admin user.
        """
        from flask import render_template, request
        if request.method == 'POST':
            store_name = request.form.get('store_name')
            store_username = request.form.get('store_username')
            store_password = request.form.get('store_password')
            admin_username = request.form.get('admin_username')
            admin_password = request.form.get('admin_password')
            
            errors = []
            if not store_name: errors.append('Store Name is required.')
            if not store_username: errors.append('Store Username is required.')
            if not store_password: errors.append('Store Password is required.')
            if not admin_username: errors.append('Admin Username is required.')
            if not admin_password: errors.append('Admin Password is required.')

            if len(store_password) < 8: errors.append('Store password must be at least 8 characters.')
            if len(admin_password) < 8: errors.append('Admin password must be at least 8 characters.')
            
            if Store.query.filter_by(username=store_username).first():
                errors.append('Store username already exists.')
            if User.query.filter_by(username=admin_username).first():
                errors.append('Admin username already exists. Please choose a different one.')
            
            if errors:
                for error in errors:
                    flash(error, 'danger')
                return render_template('store_register.html'), 400
            
            try:
                store = Store(name=store_name, username=store_username)
                store.set_password(store_password)
                db.session.add(store)
                db.session.flush()

                admin_user = User(username=admin_username, role='admin', is_admin=True, is_groomer=True, store_id=store.id)
                admin_user.set_password(admin_password)
                db.session.add(admin_user)
                db.session.commit()

                app.logger.info(f"New store '{store_name}' (ID: {store.id}) and admin user '{admin_username}' created.")
                flash('Store and admin account created! Please log in to your store.', 'success')
                return redirect(url_for('store_login'))
            except IntegrityError:
                db.session.rollback()
                app.logger.error(f"IntegrityError during store registration for store {store_username} or admin {admin_username}.", exc_info=True)
                flash("A store or admin user with that name/username already exists. Please try different names.", "danger")
                return render_template('store_register.html'), 500
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error during store registration: {e}", exc_info=True)
                flash("An unexpected error occurred during registration.", "danger")
                return render_template('store_register.html'), 500
        return render_template('store_register.html')

    # Superadmin dashboard route
    @app.route('/superadmin/dashboard')
    def superadmin_dashboard():
        """
        Displays the superadmin dashboard with a list of all stores and their admins.
        """
        from flask import render_template
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        stores = Store.query.all()
        store_admins = {store.id: User.query.filter_by(store_id=store.id, is_admin=True).all() for store in stores}
        
        app.logger.info("Superadmin viewed dashboard.")
        return render_template('superadmin_dashboard.html', stores=stores, store_admins=store_admins)

    # Superadmin tools route
    @app.route('/superadmin/tools')
    def superadmin_tools():
        """
        Displays superadmin tools page.
        """
        from flask import render_template
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
        """
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        store_to_impersonate = Store.query.get(store_id)
        if not store_to_impersonate:
            flash("Store not found for impersonation.", "danger")
            return redirect(url_for('superadmin_dashboard'))

        session['store_id'] = store_id
        session['impersonating'] = True
        app.logger.info(f"Superadmin {g.user.username} (ID: {g.user.id}) is now impersonating store ID: {store_id} ('{store_to_impersonate.name}').")
        flash(f"Now impersonating store '{store_to_impersonate.name}'.", "info")
        return redirect(url_for('dashboard'))

    # Superadmin stop impersonation
    @app.route('/superadmin/stop_impersonation')
    def superadmin_stop_impersonation():
        """
        Allows a superadmin to stop impersonating a store.
        """
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        current_impersonated_store_id = session.get('store_id')
        session.pop('store_id', None)
        session.pop('impersonating', None)
        app.logger.info(f"Superadmin {g.user.username} (ID: {g.user.id}) stopped impersonating store ID: {current_impersonated_store_id}.")
        flash('Stopped impersonating store.', 'info')
        return redirect(url_for('superadmin_dashboard'))

    # Apply ProxyFix middleware
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
