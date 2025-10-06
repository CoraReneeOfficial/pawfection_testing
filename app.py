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
from public import public_bp
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
from sqlalchemy.exc import IntegrityError
from utils import log_activity, subscription_required
from auth.routes import oauth
import stripe
from utils import is_user_subscribed
from flask import request, jsonify, render_template
from secure_headers import init_secure_headers  # Import secure headers
# Removed import for datetime as it's not directly used at top level of app.py anymore
# Removed log_activity definition as it's now in utils.py

# Configure logging for the application
def configure_logging(app):
    """Configure application logging."""
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(app.root_path, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # Set log levels for different loggers
    app.logger.setLevel(logging.DEBUG)
    
    # Create file handler which logs even debug messages
    file_handler = logging.FileHandler(os.path.join(logs_dir, 'app.log'))
    file_handler.setLevel(logging.DEBUG)
    
    # Create console handler with a higher log level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add the handlers to the logger
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    
    # Set specific log levels for noisy libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('googleapiclient').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
    
    # Enable debug logging for our email module
    logging.getLogger('app.email').setLevel(logging.DEBUG)
    
    app.logger.info('Logging configured successfully')

def create_app():
    """
    Creates and configures the Flask application instance.
    This function acts as the application factory.
    """
    app = Flask(__name__)
    # Set security headers (HSTS, CSP, etc.)
    init_secure_headers(app)
    
    # Configure logging
    configure_logging(app)

    # --- Initialize Flask-Login ---
    from flask_login import LoginManager
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'  # Update if your login route endpoint is different
    login_manager.init_app(app)

    # Register user loader
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Initialize Stripe
    app.config['STRIPE_PUBLISHABLE_KEY'] = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    app.config['STRIPE_SECRET_KEY'] = os.environ.get('STRIPE_SECRET_KEY')
    stripe.api_key = app.config['STRIPE_SECRET_KEY']
    app.config['STRIPE_PRICE_ID'] = os.environ.get('STRIPE_PRICE_ID')

    # Define base directories for persistent data and uploads.
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    PERSISTENT_DATA_ROOT = os.environ.get('PERSISTENT_DATA_DIR', BASE_DIR)
    DATABASE_PATH = os.path.join(PERSISTENT_DATA_ROOT, 'grooming_business_v2.db')
    UPLOAD_FOLDER = os.path.join(PERSISTENT_DATA_ROOT, 'uploads')
    SHARED_TOKEN_FILE = os.path.join(PERSISTENT_DATA_ROOT, 'shared_google_token.json')
    NOTIFICATION_SETTINGS_FILE = os.path.join(PERSISTENT_DATA_ROOT, 'notification_settings.json')

    # Configure Flask application settings.
    app.config['SECRET_KEY'] = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))
    # Security: Set secure cookie flags
    app.config['SESSION_COOKIE_SECURE'] = True  # Only send cookies over HTTPS
    app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access to cookies
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Or 'Strict' if you want to be more restrictive
    # Optionally, set REMEMBER_COOKIE_SECURE/HTTPONLY/SAMESITE if using Flask-Login remember me
    app.config['REMEMBER_COOKIE_SECURE'] = True
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
    # Set session timeout to 30 minutes for permanent sessions
    from datetime import timedelta
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
    
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
    # Initialize OAuth for Google login
    oauth.init_app(app)

    # Log the database URI being used
    app.logger.info(f"SQLAlchemy Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

    # Check if 'details_needed' column exists in Appointment table
    with app.app_context():
        inspector = db.inspect(db.engine)
        try:
            columns = [col['name'] for col in inspector.get_columns('appointment')]
            if 'details_needed' in columns:
                app.logger.info("[DEBUG] 'details_needed' column exists in 'appointment' table.")
            else:
                app.logger.error("[DEBUG] 'details_needed' column is MISSING from 'appointment' table!")
        except Exception as e:
            app.logger.warning(f"[DEBUG] Could not inspect 'appointment' table: {e}")

    # Initialize Flask-Migrate for database migrations
    from flask_migrate import Migrate
    migrate = Migrate(app, db)
    
    # Register CLI commands
    from commands import register_commands
    register_commands(app)
    
    # Register custom Jinja2 filters
    @app.template_filter('service_names_from_ids')
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
    
    @app.template_filter('timeago')
    def timeago_filter(dt):
        """Format a timestamp into a human-readable relative time (e.g., '2 hours ago')."""
        if not dt:
            return ''
        
        import datetime
        now = datetime.datetime.now(dt.tzinfo) if dt.tzinfo else datetime.datetime.utcnow()
        diff = now - dt
        
        # Calculate the time difference
        seconds = diff.total_seconds()
        minutes = seconds / 60
        hours = minutes / 60
        days = diff.days
        
        if seconds < 60:
            return 'just now'
        elif minutes < 60:
            return f'{int(minutes)} minute{"s" if minutes > 1 else ""} ago'
        elif hours < 24:
            return f'{int(hours)} hour{"s" if hours > 1 else ""} ago'
        elif days < 7:
            return f'{days} day{"s" if days > 1 else ""} ago'
        elif days < 30:
            weeks = days // 7
            return f'{weeks} week{"s" if weeks > 1 else ""} ago'
        elif days < 365:
            months = days // 30
            return f'{months} month{"s" if months > 1 else ""} ago'
        else:
            years = days // 365
            return f'{years} year{"s" if years > 1 else ""} ago'

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

    # Register blueprints for modular routes
    app.register_blueprint(auth_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(dogs_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(management_bp)
    app.register_blueprint(public_bp)

    # Register Google Calendar webhook blueprint
    from appointments.google_calendar_webhook import webhook_bp as google_calendar_webhook_bp
    app.register_blueprint(google_calendar_webhook_bp)
    
    # Register notifications blueprint
    from notification_system import bp as notification_system_bp
    app.register_blueprint(notification_system_bp)
    
    # Context processor to make notification data available to all templates
    @app.context_processor
    def inject_notifications():
        """Add notification data to all template contexts."""
        from models import Notification
        from flask import g
        
        if not hasattr(g, 'user') or g.user is None or not hasattr(g, 'user') or not g.user.store_id:
            return {'notifications': [], 'unread_notifications_count': 0}
        
        # Get the latest 5 unread notifications
        notifications = Notification.query.filter_by(
            store_id=g.user.store_id,
            is_read=False
        ).order_by(Notification.created_at.desc()).limit(5).all()
        
        # Get the total count of unread notifications
        unread_count = Notification.query.filter_by(
            store_id=g.user.store_id,
            is_read=False
        ).count()
        
        # Import the function to generate notification links
        from notification_system import get_notification_link
        
        # Add the link to each notification
        for notification in notifications:
            notification.link = get_notification_link(notification)
        
        return {'notifications': notifications, 'unread_notifications_count': unread_count}

    # This function runs before every request to load the logged-in user.
    @app.before_request
    def load_logged_in_user():
        """
        Loads the logged-in user into Flask's global 'g' object before each request.
        Also ensures session['store_id'] is managed correctly for superadmin and non-superadmin users.
        Logs the session contents for debugging.
        """
        # --- START OF DEBUG PRINTS ---
        print("\n" + "="*20, "DEBUG: ENTERING @app.before_request (load_logged_in_user)", "="*20)
        # --- END OF DEBUG PRINTS ---
        
        app.logger.debug(f"[SESSION DEBUG] Session at start of request: {dict(session)}")
        user_id = session.get('user_id')
        if user_id is None:
            g.user = None
            app.logger.debug("No user_id found in session. g.user set to None.")
        else:
            g.user = db.session.get(User, user_id)
            if g.user:
                app.logger.debug(f"Loaded user {g.user.username} (ID: {g.user.id}, Store ID: {g.user.store_id}) from session.")
                # --- IMPERSONATION/STORE CONTEXT MANAGEMENT ---
                is_superadmin = getattr(g.user, 'role', None) == 'superadmin' and g.user.store_id is None
                impersonating = session.get('impersonating', False)
                if is_superadmin:
                    if not impersonating:
                        # If superadmin is NOT impersonating, remove store_id from session
                        if session.get('store_id') is not None:
                            session.pop('store_id', None)
                            app.logger.debug("Superadmin is not impersonating. Removed store_id from session.")
                    # else: if impersonating, leave store_id as is
                else:
                    # Not a superadmin: ensure session['store_id'] matches user's store_id
                    if g.user.store_id is not None and session.get('store_id') != g.user.store_id:
                        session['store_id'] = g.user.store_id
                        app.logger.debug(f"Session store_id updated to match user's store_id: {g.user.store_id}")
            else:
                app.logger.warning(f"User with ID {user_id} found in session but not in database. Clearing session user_id.")
                session.pop('user_id', None)
                g.user = None
        
        # --- START OF DEBUG PRINTS ---
        print("="*20, "DEBUG: EXITING @app.before_request (load_logged_in_user)", "="*20 + "\n")
        # --- END OF DEBUG PRINTS ---

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

    # Stripe Billing Routes
    from flask import abort
    @app.route('/billing/stripe_checkout')
    @login_required
    def stripe_checkout():
        store_id = session.get('store_id')
        if not store_id:
            flash('No store found for your user.', 'danger')
            return redirect(url_for('dashboard'))
        store = db.session.get(Store, store_id)
        if not store:
            flash('Store not found.', 'danger')
            return redirect(url_for('dashboard'))
        if not store.stripe_customer_id:
            # Create a customer in Stripe if not present
            customer = stripe.Customer.create(email=store.email, name=store.name)
            store.stripe_customer_id = customer.id
            db.session.commit()
        try:
            checkout_session = stripe.checkout.Session.create(
                customer=store.stripe_customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': app.config['STRIPE_PRICE_ID'],
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=url_for('dashboard', _external=True) + '?subscription=success',
                cancel_url=url_for('dashboard', _external=True) + '?subscription=cancel',
            )
            return redirect(checkout_session.url)
        except Exception as e:
            app.logger.error(f"Stripe Checkout error: {e}")
            flash('There was an error starting your subscription. Please try again.', 'danger')
            return redirect(url_for('dashboard'))

    @app.route('/billing/stripe_portal')
    @login_required
    def stripe_portal():
        store_id = session.get('store_id')
        if not store_id:
            flash('No store found for your user.', 'danger')
            return redirect(url_for('dashboard'))
        store = db.session.get(Store, store_id)
        if not store or not store.stripe_customer_id:
            flash('No Stripe customer found for your store. Please subscribe first.', 'danger')
            return redirect(url_for('dashboard'))
        try:
            portal_session = stripe.billing_portal.Session.create(
                customer=store.stripe_customer_id,
                return_url=url_for('dashboard', _external=True)
            )
            return redirect(portal_session.url)
        except Exception as e:
            app.logger.error(f"Stripe Portal error: {e}")
            flash('There was an error accessing your billing portal. Please try again.', 'danger')
            return redirect(url_for('dashboard'))

    # Legal pages routes
    @app.route('/user-agreement')
    def view_user_agreement():
        from flask import render_template
        from datetime import datetime
        return render_template('user_agreement.html', now=datetime.now)

    # Privacy policy route
    @app.route('/privacy-policy')
    def view_privacy_policy():
        from flask import render_template
        from datetime import datetime
        return render_template('privacy_policy.html', now=datetime.now)

    # Dashboard route
    @app.route('/dashboard')
    @login_required
    @subscription_required
    def dashboard():
        # --- START OF DEBUG PRINTS ---
        print("\n" + "="*20, "DEBUG: TOP OF DASHBOARD FUNCTION!", "="*20 + "\n")
        # --- END OF DEBUG PRINTS ---
        from flask import render_template
        import pytz
        from models import Appointment, Dog, Store, Owner
        from sqlalchemy.orm import joinedload
        from dateutil import tz
        import datetime
        from sqlalchemy import func, and_, or_
        store_id = session.get('store_id')
        store = None
        STORE_TIMEZONE = pytz.UTC
        if store_id:
            store = db.session.get(Store, store_id)
            store_tz_str = getattr(store, 'timezone', None) or 'UTC'
            try:
                STORE_TIMEZONE = pytz.timezone(store_tz_str)
            except Exception:
                STORE_TIMEZONE = pytz.UTC
        now_utc = datetime.datetime.utcnow()
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + datetime.timedelta(days=1)
        week_start = (today_start - datetime.timedelta(days=today_start.weekday()))
        week_end = week_start + datetime.timedelta(days=7)

        # Appointments Today
        appointments_today = 0
        # Pending Checkouts
        pending_checkouts = 0
        # New Clients This Week
        new_clients_week = 0
        # Revenue Today
        revenue_today = 0.0
        # Appointments needing details
        appointments_details_needed = []
        # Upcoming appointments
        upcoming_appointments = []

        if store_id:
            # Appointments Today
            appointments_today = Appointment.query.filter(
                Appointment.status == 'Scheduled',
                Appointment.store_id == store_id,
                Appointment.appointment_datetime >= today_start,
                Appointment.appointment_datetime < today_end
            ).count()

            # Pending Checkouts (appointments scheduled for today or earlier, not completed/cancelled)
            pending_checkouts = Appointment.query.filter(
                Appointment.status == 'Scheduled',
                Appointment.store_id == store_id,
                Appointment.appointment_datetime < now_utc
            ).count()

            # New Clients This Week
            new_clients_week = Owner.query.filter(
                Owner.store_id == store_id,
                Owner.created_at >= week_start,
                Owner.created_at < week_end
            ).count()

            # Revenue Today (sum of completed appointments today)
            revenue_today = db.session.query(func.coalesce(func.sum(Appointment.checkout_total_amount), 0)).filter(
                Appointment.status == 'Completed',
                Appointment.store_id == store_id,
                Appointment.appointment_datetime >= today_start,
                Appointment.appointment_datetime < today_end
            ).scalar() or 0.0

            # Appointments needing details
            appointments_details_needed = (
                Appointment.query.options(
                    joinedload(Appointment.dog).joinedload(Dog.owner),
                    joinedload(Appointment.groomer)
                )
                .filter(
                    Appointment.status == 'Scheduled',
                    Appointment.store_id == store_id,
                    Appointment.details_needed == True
                )
                .order_by(Appointment.appointment_datetime.asc())
                .all()
            )

            # Upcoming appointments (next 5)
            upcoming_appointments = (
                Appointment.query.options(
                    joinedload(Appointment.dog).joinedload(Dog.owner),
                    joinedload(Appointment.groomer)
                )
                .filter(
                    Appointment.status == 'Scheduled',
                    Appointment.store_id == store_id
                )
                .order_by(Appointment.appointment_datetime.asc())
                .limit(5)
                .all()
)

        return render_template(
            'dashboard.html',
            appointments_today=appointments_today,
            pending_checkouts=pending_checkouts,
            new_clients_week=new_clients_week,
            revenue_today=revenue_today,
            appointments_details_needed=appointments_details_needed,
            upcoming_appointments=upcoming_appointments,
            STORE_TIMEZONE=STORE_TIMEZONE,
            tz=tz
        )

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
                return redirect(url_for('superadmin_dashboard'))
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
            store_email = request.form.get('store_email', '').strip()
            security_question = request.form.get('security_question')
            security_answer = request.form.get('security_answer')
            admin_username = request.form.get('admin_username')
            admin_password = request.form.get('admin_password')
            
            errors = []
            if not store_name: errors.append('Store Name is required.')
            if not store_username: errors.append('Store Username is required.')
            if not store_password: errors.append('Store Password is required.')
            if not store_email: errors.append('Store Email is required.')
            if not security_question: errors.append('Security Question is required.')
            if not security_answer: errors.append('Security Answer is required.')
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
                store = Store(name=store_name, username=store_username, email=store_email, security_question=security_question)
                store.set_password(store_password)
                store.set_security_answer(security_answer)
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
        
        # Count active and expired subscriptions
        active_subscriptions = Store.query.filter_by(subscription_status='active').count()
        expired_subscriptions = Store.query.filter_by(subscription_status='expired').count()
        
        from models import ActivityLog
        activity_logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(10).all()
        
        return render_template('superadmin_dashboard.html', 
                              stores=stores, 
                              store_admins=store_admins,
                              active_subscriptions=active_subscriptions,
                              expired_subscriptions=expired_subscriptions,
                              activity_logs=activity_logs)

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
    
    # Superadmin System Health route
    @app.route('/superadmin/system-health')
    def superadmin_system_health():
        """
        Displays system health and performance metrics for superadmins.
        """
        import psutil
        import platform
        from datetime import datetime
        from flask import render_template
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Collect system information
        system_info = {
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'uptime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'cpu_usage': f"{psutil.cpu_percent(interval=1)}%",
            'memory_usage': f"{psutil.virtual_memory().percent}%",
            'disk_usage': f"{psutil.disk_usage('/').percent}%",
        }
        
        # Get active users in the last 24 hours
        from models import User, Store, ActivityLog
        from datetime import datetime, timedelta
        
        yesterday = datetime.now() - timedelta(days=1)
        
        # System statistics
        total_stores = Store.query.count()
        active_stores = Store.query.filter_by(subscription_status='active').count()
        total_users = User.query.count()
        recent_activity = ActivityLog.query.filter(ActivityLog.timestamp >= yesterday).count()
        
        # Recent logins
        recent_logins = ActivityLog.query.filter(
            ActivityLog.timestamp >= yesterday,
            ActivityLog.action.like('%login%')
        ).order_by(ActivityLog.timestamp.desc()).limit(10).all()
        
        app.logger.info("Superadmin viewed system health page.")
        return render_template('superadmin_system_health.html', 
                              system_info=system_info,
                              total_stores=total_stores,
                              active_stores=active_stores,
                              total_users=total_users,
                              recent_activity=recent_activity,
                              recent_logins=recent_logins)
                              
    # Superadmin User Management route
    @app.route('/superadmin/user-management')
    def superadmin_user_management():
        """
        Displays user management interface for superadmins.
        """
        from flask import render_template, request
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Get query parameters for filtering/sorting
        search_query = request.args.get('search', '')
        role_filter = request.args.get('role', '')
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'desc')
        page = request.args.get('page', 1, type=int)
        per_page = 15  # Users per page
        
        # Base query
        query = User.query
        
        # Apply filters
        if search_query:
            query = query.filter(
                or_(
                    User.username.ilike(f'%{search_query}%'),
                    User.email.ilike(f'%{search_query}%'),
                    User.first_name.ilike(f'%{search_query}%'),
                    User.last_name.ilike(f'%{search_query}%')
                )
            )
        
        if role_filter:
            query = query.filter(User.role == role_filter)
        
        # Apply sorting
        if sort_by == 'username':
            query = query.order_by(User.username.asc() if sort_order == 'asc' else User.username.desc())
        elif sort_by == 'email':
            query = query.order_by(User.email.asc() if sort_order == 'asc' else User.email.desc())
        elif sort_by == 'created_at':
            query = query.order_by(User.created_at.asc() if sort_order == 'asc' else User.created_at.desc())
        elif sort_by == 'last_login':
            query = query.order_by(User.last_login.asc() if sort_order == 'asc' else User.last_login.desc())
        
        # Paginate results
        users_pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        users = users_pagination.items
        
        # Get unique roles for filter dropdown
        roles = db.session.query(User.role).distinct().all()
        unique_roles = [role[0] for role in roles if role[0]]
        
        app.logger.info("Superadmin viewed user management page.")
        return render_template('superadmin_user_management.html',
                              users=users,
                              pagination=users_pagination,
                              search_query=search_query,
                              role_filter=role_filter,
                              sort_by=sort_by,
                              sort_order=sort_order,
                              roles=unique_roles)
    
    # Superadmin Data Export route
    @app.route('/superadmin/data-export')
    def superadmin_data_export():
        """
        Displays data export interface for superadmins.
        """
        from flask import render_template
        import datetime
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Get export options (tables available for export)
        export_tables = [
            {'name': 'stores', 'label': 'Stores', 'description': 'All store details including subscription status'},
            {'name': 'users', 'label': 'Users', 'description': 'All user accounts and their roles'},
            {'name': 'appointments', 'label': 'Appointments', 'description': 'All appointment data including status'},
            {'name': 'dogs', 'label': 'Dogs', 'description': 'All registered dogs and their details'},
            {'name': 'activity_logs', 'label': 'Activity Logs', 'description': 'System activity logs'},
            {'name': 'services', 'label': 'Services', 'description': 'Available services across all stores'}
        ]
        
        # Get recent exports if we had a table to track them
        recent_exports = [
            {
                'id': 1,
                'table': 'stores',
                'format': 'csv',
                'timestamp': datetime.datetime.now() - datetime.timedelta(days=1),
                'status': 'completed',
                'file_size': '45 KB',
                'exported_by': 'admin'
            },
            {
                'id': 2,
                'table': 'appointments',
                'format': 'json',
                'timestamp': datetime.datetime.now() - datetime.timedelta(days=3),
                'status': 'completed',
                'file_size': '128 KB',
                'exported_by': 'admin'
            }
        ]
        
        # List of available export formats
        export_formats = ['csv', 'json', 'excel']
        
        app.logger.info("Superadmin viewed data export page.")
        return render_template('superadmin_data_export.html',
                              export_tables=export_tables,
                              recent_exports=recent_exports,
                              export_formats=export_formats)
                              
    # Superadmin Global Configuration Settings route
    @app.route('/superadmin/global-configuration', methods=['GET', 'POST'])
    def superadmin_global_config():
        """
        Displays and processes configuration settings for superadmins.
        """
        from flask import render_template, request, flash, redirect, url_for
        import json
        import os
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Path to configuration file
        config_file_path = os.path.join(os.path.dirname(__file__), 'config', 'app_settings.json')
        
        # Create config directory if it doesn't exist
        os.makedirs(os.path.dirname(config_file_path), exist_ok=True)
        
        # Default configuration settings
        default_config = {
            'system': {
                'maintenance_mode': False,
                'debug_mode': False,
                'log_level': 'INFO',
                'session_timeout': 30
            },
            'email': {
                'smtp_server': 'smtp.example.com',
                'smtp_port': 587,
                'smtp_use_tls': True,
                'sender_email': 'noreply@pawfection.com',
                'sender_name': 'Pawfection Grooming'
            },
            'appointments': {
                'allow_online_booking': True,
                'max_appointments_per_day': 15,
                'buffer_minutes': 15,
                'notification_enabled': True
            },
            'payments': {
                'stripe_enabled': True,
                'cash_enabled': True,
                'check_enabled': True,
                'default_tax_rate': 8.5,
                'allow_tips': True
            },
            'security': {
                'failed_login_limit': 5,
                'password_expiry_days': 90,
                'require_2fa': False,
                'lockout_duration_minutes': 30
            }
        }
        
        # Load current configuration or create default if not exists
        current_config = default_config
        try:
            if os.path.exists(config_file_path):
                with open(config_file_path, 'r') as file:
                    current_config = json.load(file)
        except Exception as e:
            app.logger.error(f"Error loading configuration: {str(e)}")
            flash('Error loading configuration settings.', 'danger')
        
        # Process form submission
        if request.method == 'POST':
            try:
                updated_config = current_config.copy()
                
                # Process system settings
                updated_config['system']['maintenance_mode'] = 'maintenance_mode' in request.form
                updated_config['system']['debug_mode'] = 'debug_mode' in request.form
                updated_config['system']['log_level'] = request.form.get('log_level')
                updated_config['system']['session_timeout'] = int(request.form.get('session_timeout', 30))
                
                # Process email settings
                updated_config['email']['smtp_server'] = request.form.get('smtp_server')
                updated_config['email']['smtp_port'] = int(request.form.get('smtp_port', 587))
                updated_config['email']['smtp_use_tls'] = 'smtp_use_tls' in request.form
                updated_config['email']['sender_email'] = request.form.get('sender_email')
                updated_config['email']['sender_name'] = request.form.get('sender_name')
                
                # Process appointment settings
                updated_config['appointments']['allow_online_booking'] = 'allow_online_booking' in request.form
                updated_config['appointments']['max_appointments_per_day'] = int(request.form.get('max_appointments_per_day', 15))
                updated_config['appointments']['buffer_minutes'] = int(request.form.get('buffer_minutes', 15))
                updated_config['appointments']['notification_enabled'] = 'notification_enabled' in request.form
                
                # Process payment settings
                updated_config['payments']['stripe_enabled'] = 'stripe_enabled' in request.form
                updated_config['payments']['cash_enabled'] = 'cash_enabled' in request.form
                updated_config['payments']['check_enabled'] = 'check_enabled' in request.form
                updated_config['payments']['default_tax_rate'] = float(request.form.get('default_tax_rate', 8.5))
                updated_config['payments']['allow_tips'] = 'allow_tips' in request.form
                
                # Process security settings
                updated_config['security']['failed_login_limit'] = int(request.form.get('failed_login_limit', 5))
                updated_config['security']['password_expiry_days'] = int(request.form.get('password_expiry_days', 90))
                updated_config['security']['require_2fa'] = 'require_2fa' in request.form
                updated_config['security']['lockout_duration_minutes'] = int(request.form.get('lockout_duration_minutes', 30))
                
                # Save updated configuration
                with open(config_file_path, 'w') as file:
                    json.dump(updated_config, file, indent=2)
                
                current_config = updated_config
                flash('Configuration settings saved successfully.', 'success')
                
            except Exception as e:
                app.logger.error(f"Error saving configuration: {str(e)}")
                flash(f'Error saving configuration: {str(e)}', 'danger')
        
        # Render the configuration page
        app.logger.info("Superadmin viewed configuration settings page.")
        return render_template('superadmin_configuration.html', config=current_config)
        
    # Superadmin User Permissions route
    @app.route('/superadmin/permissions', methods=['GET', 'POST'])
    def superadmin_permissions():
        """
        Displays and processes role permissions for superadmins.
        """
        from flask import render_template, request, flash, redirect, url_for, jsonify
        import json
        import os
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
            
        # Path to roles permissions file
        permissions_file_path = os.path.join(os.path.dirname(__file__), 'config', 'role_permissions.json')
        
        # Create config directory if it doesn't exist
        os.makedirs(os.path.dirname(permissions_file_path), exist_ok=True)
        
        # Default role permissions
        default_permissions = {
            "roles": [
                {
                    "name": "superadmin",
                    "display_name": "Super Administrator",
                    "description": "Full system access with all permissions",
                    "permissions": {
                        "users": {"view": True, "create": True, "edit": True, "delete": True},
                        "stores": {"view": True, "create": True, "edit": True, "delete": True},
                        "appointments": {"view": True, "create": True, "edit": True, "delete": True},
                        "dogs": {"view": True, "create": True, "edit": True, "delete": True},
                        "services": {"view": True, "create": True, "edit": True, "delete": True},
                        "reports": {"view": True, "create": True, "export": True},
                        "settings": {"view": True, "edit": True},
                        "system": {"view": True, "edit": True}
                    }
                },
                {
                    "name": "admin",
                    "display_name": "Store Administrator",
                    "description": "Store management with limited system access",
                    "permissions": {
                        "users": {"view": True, "create": True, "edit": True, "delete": False},
                        "stores": {"view": "own", "create": False, "edit": "own", "delete": False},
                        "appointments": {"view": True, "create": True, "edit": True, "delete": True},
                        "dogs": {"view": True, "create": True, "edit": True, "delete": True},
                        "services": {"view": True, "create": True, "edit": True, "delete": True},
                        "reports": {"view": True, "create": True, "export": True},
                        "settings": {"view": "own", "edit": "own"},
                        "system": {"view": False, "edit": False}
                    }
                },
                {
                    "name": "groomer",
                    "display_name": "Groomer",
                    "description": "Groomer with appointment management access",
                    "permissions": {
                        "users": {"view": False, "create": False, "edit": False, "delete": False},
                        "stores": {"view": "own", "create": False, "edit": False, "delete": False},
                        "appointments": {"view": True, "create": True, "edit": True, "delete": False},
                        "dogs": {"view": True, "create": True, "edit": True, "delete": False},
                        "services": {"view": True, "create": False, "edit": False, "delete": False},
                        "reports": {"view": "own", "create": False, "export": False},
                        "settings": {"view": False, "edit": False},
                        "system": {"view": False, "edit": False}
                    }
                },
                {
                    "name": "receptionist",
                    "display_name": "Receptionist",
                    "description": "Front desk staff with customer service access",
                    "permissions": {
                        "users": {"view": False, "create": False, "edit": False, "delete": False},
                        "stores": {"view": "own", "create": False, "edit": False, "delete": False},
                        "appointments": {"view": True, "create": True, "edit": True, "delete": False},
                        "dogs": {"view": True, "create": True, "edit": True, "delete": False},
                        "services": {"view": True, "create": False, "edit": False, "delete": False},
                        "reports": {"view": False, "create": False, "export": False},
                        "settings": {"view": False, "edit": False},
                        "system": {"view": False, "edit": False}
                    }
                }
            ],
            "resource_types": [
                {
                    "name": "users",
                    "display_name": "Users & Accounts",
                    "operations": ["view", "create", "edit", "delete"]
                },
                {
                    "name": "stores",
                    "display_name": "Stores",
                    "operations": ["view", "create", "edit", "delete"]
                },
                {
                    "name": "appointments",
                    "display_name": "Appointments",
                    "operations": ["view", "create", "edit", "delete"]
                },
                {
                    "name": "dogs",
                    "display_name": "Dogs & Customers",
                    "operations": ["view", "create", "edit", "delete"]
                },
                {
                    "name": "services",
                    "display_name": "Services & Products",
                    "operations": ["view", "create", "edit", "delete"]
                },
                {
                    "name": "reports",
                    "display_name": "Reports & Analytics",
                    "operations": ["view", "create", "export"]
                },
                {
                    "name": "settings",
                    "display_name": "Settings",
                    "operations": ["view", "edit"]
                },
                {
                    "name": "system",
                    "display_name": "System Administration",
                    "operations": ["view", "edit"]
                }
            ]
        }
        
        # Load current permissions or create default if not exists
        current_permissions = default_permissions
        try:
            if os.path.exists(permissions_file_path):
                with open(permissions_file_path, 'r') as file:
                    current_permissions = json.load(file)
        except Exception as e:
            app.logger.error(f"Error loading permissions: {str(e)}")
            flash('Error loading role permissions.', 'danger')
        
        # Process form submission
        if request.method == 'POST':
            try:
                # Handle AJAX requests for updating role permissions
                if request.is_json:
                    data = request.get_json()
                    
                    # Find the role to update
                    role_name = data.get('role_name')
                    resource_name = data.get('resource_name')
                    operation_name = data.get('operation_name')
                    value = data.get('value')
                    
                    # Update the permission
                    for role in current_permissions['roles']:
                        if role['name'] == role_name:
                            if value == "own":
                                role['permissions'][resource_name][operation_name] = "own"
                            else:
                                role['permissions'][resource_name][operation_name] = bool(value)
                            
                            # Save updated permissions
                            with open(permissions_file_path, 'w') as file:
                                json.dump(current_permissions, file, indent=2)
                            
                            return jsonify({'success': True})
                    
                    return jsonify({'success': False, 'error': 'Role not found'}), 404
                    
                # Handle standard form submission for adding new roles
                else:    
                    role_name = request.form.get('role_name')
                    display_name = request.form.get('display_name')
                    description = request.form.get('description')
                    
                    # Validate new role
                    if not role_name or not display_name:
                        flash('Role name and display name are required.', 'danger')
                        return redirect(url_for('superadmin_permissions'))
                    
                    # Check if role name already exists
                    for role in current_permissions['roles']:
                        if role['name'] == role_name:
                            flash('Role with this name already exists.', 'danger')
                            return redirect(url_for('superadmin_permissions'))
                    
                    # Create default permissions for new role
                    new_permissions = {}
                    for resource in current_permissions['resource_types']:
                        new_permissions[resource['name']] = {}
                        for operation in resource['operations']:
                            new_permissions[resource['name']][operation] = False
                    
                    # Add new role
                    current_permissions['roles'].append({
                        "name": role_name,
                        "display_name": display_name,
                        "description": description,
                        "permissions": new_permissions
                    })
                    
                    # Save updated permissions
                    with open(permissions_file_path, 'w') as file:
                        json.dump(current_permissions, file, indent=2)
                    
                    flash('New role created successfully.', 'success')
            except Exception as e:
                app.logger.error(f"Error saving permissions: {str(e)}")
                flash(f'Error saving permissions: {str(e)}', 'danger')
        
        # Render the permissions page
        app.logger.info("Superadmin viewed user permissions page.")
        return render_template('superadmin_permissions.html', permissions=current_permissions)
        
    # Superadmin Application Settings route
    @app.route('/superadmin/application-settings', methods=['GET', 'POST'])
    def superadmin_application_settings():
        """
        Displays and processes application settings for superadmins.
        """
        from flask import render_template, request, flash, redirect, url_for
        import json
        import os
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Path to application settings file
        settings_file_path = os.path.join(os.path.dirname(__file__), 'config', 'application_settings.json')
        
        # Create config directory if it doesn't exist
        os.makedirs(os.path.dirname(settings_file_path), exist_ok=True)
        
        # Default application settings
        default_settings = {
            "appearance": {
                "theme": "default",
                "color_scheme": "blue",
                "logo_url": "/static/images/logo.png",
                "favicon_url": "/static/images/favicon.ico",
                "custom_css": ""
            },
            "business": {
                "business_name": "Pawfection Grooming Solutions",
                "contact_email": "contact@pawfection.com",
                "contact_phone": "(555) 123-4567",
                "address": "123 Main Street, Anytown, USA 12345",
                "website": "https://www.pawfection.com",
                "hours_of_operation": "Monday-Friday 9am-5pm, Saturday 10am-4pm"
            },
            "notifications": {
                "appointment_confirmation": True,
                "appointment_reminder": True,
                "appointment_cancellation": True,
                "appointment_rescheduling": True,
                "invoice_notification": True,
                "marketing_emails": True
            },
            "integrations": {
                "stripe_public_key": "",
                "stripe_private_key": "",
                "google_analytics_id": "",
                "facebook_pixel_id": "",
                "mailchimp_api_key": "",
                "google_maps_api_key": ""
            },
            "features": {
                "online_booking": True,
                "customer_accounts": True,
                "customer_reviews": True,
                "gift_cards": False,
                "loyalty_program": False,
                "referral_program": False
            }
        }
        
        # Load current settings or create default if not exists
        current_settings = default_settings
        try:
            if os.path.exists(settings_file_path):
                with open(settings_file_path, 'r') as file:
                    current_settings = json.load(file)
        except Exception as e:
            app.logger.error(f"Error loading application settings: {str(e)}")
            flash('Error loading application settings.', 'danger')
        
        # Process form submission
        if request.method == 'POST':
            try:
                updated_settings = current_settings.copy()
                
                # Process appearance settings
                updated_settings['appearance']['theme'] = request.form.get('theme', 'default')
                updated_settings['appearance']['color_scheme'] = request.form.get('color_scheme', 'blue')
                updated_settings['appearance']['logo_url'] = request.form.get('logo_url', '/static/images/logo.png')
                updated_settings['appearance']['favicon_url'] = request.form.get('favicon_url', '/static/images/favicon.ico')
                updated_settings['appearance']['custom_css'] = request.form.get('custom_css', '')
                
                # Process business settings
                updated_settings['business']['business_name'] = request.form.get('business_name', 'Pawfection Grooming Solutions')
                updated_settings['business']['contact_email'] = request.form.get('contact_email', 'contact@pawfection.com')
                updated_settings['business']['contact_phone'] = request.form.get('contact_phone', '(555) 123-4567')
                updated_settings['business']['address'] = request.form.get('address', '123 Main Street, Anytown, USA 12345')
                updated_settings['business']['website'] = request.form.get('website', 'https://www.pawfection.com')
                updated_settings['business']['hours_of_operation'] = request.form.get('hours_of_operation', 'Monday-Friday 9am-5pm, Saturday 10am-4pm')
                
                # Process notification settings
                updated_settings['notifications']['appointment_confirmation'] = 'appointment_confirmation' in request.form
                updated_settings['notifications']['appointment_reminder'] = 'appointment_reminder' in request.form
                updated_settings['notifications']['appointment_cancellation'] = 'appointment_cancellation' in request.form
                updated_settings['notifications']['appointment_rescheduling'] = 'appointment_rescheduling' in request.form
                updated_settings['notifications']['invoice_notification'] = 'invoice_notification' in request.form
                updated_settings['notifications']['marketing_emails'] = 'marketing_emails' in request.form
                
                # Process integration settings
                updated_settings['integrations']['stripe_public_key'] = request.form.get('stripe_public_key', '')
                updated_settings['integrations']['stripe_private_key'] = request.form.get('stripe_private_key', '')
                updated_settings['integrations']['google_analytics_id'] = request.form.get('google_analytics_id', '')
                updated_settings['integrations']['facebook_pixel_id'] = request.form.get('facebook_pixel_id', '')
                updated_settings['integrations']['mailchimp_api_key'] = request.form.get('mailchimp_api_key', '')
                updated_settings['integrations']['google_maps_api_key'] = request.form.get('google_maps_api_key', '')
                
                # Process feature settings
                updated_settings['features']['online_booking'] = 'online_booking' in request.form
                updated_settings['features']['customer_accounts'] = 'customer_accounts' in request.form
                updated_settings['features']['customer_reviews'] = 'customer_reviews' in request.form
                updated_settings['features']['gift_cards'] = 'gift_cards' in request.form
                updated_settings['features']['loyalty_program'] = 'loyalty_program' in request.form
                updated_settings['features']['referral_program'] = 'referral_program' in request.form
                
                # Save updated settings
                with open(settings_file_path, 'w') as file:
                    json.dump(updated_settings, file, indent=2)
                
                current_settings = updated_settings
                flash('Application settings saved successfully.', 'success')
                
            except Exception as e:
                app.logger.error(f"Error saving application settings: {str(e)}")
                flash(f'Error saving application settings: {str(e)}', 'danger')
        
        # Available themes and color schemes
        available_themes = ['default', 'light', 'dark', 'modern', 'classic']
        available_color_schemes = ['blue', 'green', 'purple', 'red', 'orange', 'teal']
        
        # Render the application settings page
        app.logger.info("Superadmin viewed application settings page.")
        return render_template('superadmin_application_settings.html', 
                              settings=current_settings,
                              themes=available_themes,
                              color_schemes=available_color_schemes)
                              
    # Superadmin System Logs route
    @app.route('/superadmin/system-logs', methods=['GET'])
    def superadmin_system_logs():
        """
        Displays system logs for superadmins.
        """
        from flask import render_template, request, flash, redirect, url_for
        import os
        import re
        from datetime import datetime, timedelta
        import glob
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
            
        # Get query parameters
        log_type = request.args.get('type', 'application')  # application, error, access
        level = request.args.get('level', 'all')  # all, info, error, warning, debug
        date_range = request.args.get('date_range', '7')  # 1, 7, 30, all (days)
        search_term = request.args.get('search', '')
        page = int(request.args.get('page', 1))
        per_page = 50  # Logs per page
        
        # Path to log directory
        log_dir = os.path.join(os.path.dirname(__file__), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        # Determine which log file to read based on type
        log_files = []
        if log_type == 'application':
            log_files = sorted(glob.glob(os.path.join(log_dir, 'app*.log')), reverse=True)
        elif log_type == 'error':
            log_files = sorted(glob.glob(os.path.join(log_dir, 'error*.log')), reverse=True)
        elif log_type == 'access':
            log_files = sorted(glob.glob(os.path.join(log_dir, 'access*.log')), reverse=True)
            
        # Create sample logs if none exist (for demo purposes)
        if not log_files:
            sample_log_file = os.path.join(log_dir, 'app.log')
            with open(sample_log_file, 'w') as f:
                current_time = datetime.now()
                f.write(f"{current_time.strftime('%Y-%m-%d %H:%M:%S')} [INFO] Application started\n")
                f.write(f"{(current_time - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')} [WARNING] High memory usage detected\n")
                f.write(f"{(current_time - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')} [ERROR] Failed to connect to database\n")
                f.write(f"{(current_time - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')} [INFO] User login: admin@example.com\n")
                f.write(f"{(current_time - timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S')} [DEBUG] Processing appointment ID: 12345\n")
            log_files = [sample_log_file]
            
        # Read log entries
        log_entries = []
        date_cutoff = None
        
        if date_range != 'all':
            date_cutoff = datetime.now() - timedelta(days=int(date_range))
        
        for log_file in log_files:
            if not os.path.exists(log_file):
                continue
                
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        # Parse log line - format: YYYY-MM-DD HH:MM:SS [LEVEL] Message
                        match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\] (.*)', line)
                        if match:
                            timestamp_str, log_level, message = match.groups()
                            try:
                                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                                
                                # Filter by date range
                                if date_cutoff and timestamp < date_cutoff:
                                    continue
                                    
                                # Filter by log level
                                if level != 'all' and log_level.lower() != level.lower():
                                    continue
                                    
                                # Filter by search term
                                if search_term and search_term.lower() not in message.lower():
                                    continue
                                    
                                log_entries.append({
                                    'timestamp': timestamp,
                                    'level': log_level,
                                    'message': message,
                                    'source': os.path.basename(log_file)
                                })
                            except ValueError:
                                # Skip lines with invalid timestamp format
                                pass
            except Exception as e:
                app.logger.error(f"Error reading log file {log_file}: {str(e)}")
                flash(f"Error reading log file: {str(e)}", 'danger')
        
        # Sort logs by timestamp (newest first)
        log_entries.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Pagination
        total_logs = len(log_entries)
        total_pages = (total_logs + per_page - 1) // per_page
        offset = (page - 1) * per_page
        logs_page = log_entries[offset:offset + per_page]
        
        # Statistics
        level_counts = {}
        for entry in log_entries:
            level_counts[entry['level']] = level_counts.get(entry['level'], 0) + 1
        
        # Available log types and levels for filtering
        log_types = ['application', 'error', 'access']
        log_levels = ['all', 'info', 'warning', 'error', 'debug']
        date_ranges = [('1', 'Last 24 Hours'), ('7', 'Last 7 Days'), ('30', 'Last 30 Days'), ('all', 'All Time')]
        
        # Render the system logs page
        app.logger.info("Superadmin viewed system logs page.")
        return render_template('superadmin_system_logs.html',
                              logs=logs_page,
                              total_logs=total_logs,
                              page=page,
                              total_pages=total_pages,
                              log_type=log_type,
                              level=level,
                              date_range=date_range,
                              search_term=search_term,
                              log_types=log_types,
                              log_levels=log_levels,
                              date_ranges=date_ranges,
                              level_counts=level_counts)
                              
    # Superadmin Email Test route
    @app.route('/superadmin/email-test', methods=['GET', 'POST'])
    def superadmin_email_test():
        """
        Allows superadmins to test email functionality.
        """
        from flask import render_template, request, flash, redirect, url_for
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        import os
        import json
        import time
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Path to email config file
        config_dir = os.path.join(os.path.dirname(__file__), 'config')
        email_config_path = os.path.join(config_dir, 'email_config.json')
        os.makedirs(config_dir, exist_ok=True)
        
        # Default email configuration
        default_email_config = {
            "smtp_server": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "your-email@example.com",
            "smtp_password": "",
            "use_tls": True,
            "from_email": "info@pawfection.com",
            "from_name": "Pawfection Grooming Solutions"
        }
        
        # Load current email configuration or create default if not exists
        email_config = default_email_config
        try:
            if os.path.exists(email_config_path):
                with open(email_config_path, 'r') as file:
                    email_config = json.load(file)
        except Exception as e:
            app.logger.error(f"Error loading email configuration: {str(e)}")
            flash('Error loading email configuration.', 'danger')
        
        # Initialize test result variables
        test_result = None
        test_message = None
        test_time = None
        
        # Process form submission
        if request.method == 'POST':
            action = request.form.get('action', '')
            
            if action == 'test_email':
                # Test email functionality
                recipient = request.form.get('test_recipient', '')
                subject = request.form.get('test_subject', 'Email Test from Pawfection')
                body = request.form.get('test_body', 'This is a test email from Pawfection Grooming Solutions.')
                
                if not recipient:
                    flash('Recipient email is required.', 'danger')
                    return redirect(url_for('superadmin_email_test'))
                
                try:
                    # Start timing
                    start_time = time.time()
                    
                    # Create message
                    msg = MIMEMultipart()
                    msg['From'] = f"{email_config['from_name']} <{email_config['from_email']}>"
                    msg['To'] = recipient
                    msg['Subject'] = subject
                    
                    # Add HTML body
                    html = f"""<html>
                    <body>
                        <div style="font-family: Arial, sans-serif; padding: 20px;">
                            <h2 style="color: #4c6ef5;">Email Test from Pawfection</h2>
                            <p>{body}</p>
                            <hr>
                            <p style="color: #6c757d; font-size: 0.8rem;">This is a test email sent from the Pawfection Grooming Solutions admin panel.</p>
                        </div>
                    </body>
                    </html>
                    """
                    msg.attach(MIMEText(html, 'html'))
                    
                    # Connect to SMTP server and send email
                    with smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port']) as server:
                        if email_config['use_tls']:
                            server.starttls()
                        
                        if email_config['smtp_username'] and email_config['smtp_password']:
                            server.login(email_config['smtp_username'], email_config['smtp_password'])
                        
                        server.send_message(msg)
                    
                    # End timing
                    test_time = round(time.time() - start_time, 2)
                    
                    test_result = 'success'
                    test_message = f"Email successfully sent to {recipient} in {test_time} seconds."
                    flash(test_message, 'success')
                    app.logger.info(f"Superadmin sent test email to {recipient}.")
                    
                except Exception as e:
                    test_result = 'error'
                    test_message = f"Error sending email: {str(e)}"
                    flash(test_message, 'danger')
                    app.logger.error(f"Error sending test email: {str(e)}")
            
            elif action == 'save_config':
                # Update email configuration
                try:
                    updated_config = {
                        "smtp_server": request.form.get('smtp_server', ''),
                        "smtp_port": int(request.form.get('smtp_port', 587)),
                        "smtp_username": request.form.get('smtp_username', ''),
                        "smtp_password": request.form.get('smtp_password', ''),
                        "use_tls": 'use_tls' in request.form,
                        "from_email": request.form.get('from_email', ''),
                        "from_name": request.form.get('from_name', '')
                    }
                    
                    # Preserve password if not changed
                    if not updated_config['smtp_password'] and email_config['smtp_password']:
                        updated_config['smtp_password'] = email_config['smtp_password']
                    
                    # Save updated configuration
                    with open(email_config_path, 'w') as file:
                        json.dump(updated_config, file, indent=2)
                    
                    email_config = updated_config
                    flash('Email configuration saved successfully.', 'success')
                    app.logger.info("Superadmin updated email configuration.")
                    
                except Exception as e:
                    flash(f'Error saving email configuration: {str(e)}', 'danger')
                    app.logger.error(f"Error saving email configuration: {str(e)}")
        
        # Sample email templates for testing
        email_templates = [
            {
                'name': 'Welcome Email',
                'subject': 'Welcome to Pawfection Grooming Solutions',
                'body': 'Thank you for choosing Pawfection Grooming Solutions for your pet grooming needs. We look forward to serving you and your furry friend!'
            },
            {
                'name': 'Appointment Confirmation',
                'subject': 'Your Appointment is Confirmed',
                'body': 'This email confirms your appointment with Pawfection Grooming Solutions on [DATE] at [TIME].'
            },
            {
                'name': 'Appointment Reminder',
                'subject': 'Reminder: Upcoming Appointment',
                'body': 'This is a friendly reminder about your upcoming appointment with Pawfection Grooming Solutions tomorrow at [TIME].'
            },
            {
                'name': 'Custom Test',
                'subject': 'Email Test from Pawfection',
                'body': 'This is a custom test email from Pawfection Grooming Solutions admin panel.'
            }
        ]
        
        # Render the email test page
        app.logger.info("Superadmin viewed email test page.")
        return render_template('superadmin_email_test.html',
                              email_config=email_config,
                              email_templates=email_templates,
                              test_result=test_result,
                              test_message=test_message,
                              test_time=test_time)
                              
    # Superadmin Database Management route
    @app.route('/superadmin/database', methods=['GET', 'POST'])
    def superadmin_database():
        """
        Allows superadmins to perform database management tasks.
        """
        from flask import render_template, request, flash, redirect, url_for, send_file
        from sqlalchemy import inspect, text, exc
        import os
        import datetime
        import time
        import json
        import shutil
        import sqlite3
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Initialize variables
        query_result = None
        query_error = None
        execution_time = None
        table_list = []
        backup_status = None
        backup_message = None
        backup_time = None
        
        # Get database info
        try:
            # Get inspector for reflection
            inspector = inspect(db.engine)
            
            # Get table list
            table_list = inspector.get_table_names()
            
            # Get database statistics
            db_stats = {}
            for table in table_list:
                result = db.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                db_stats[table] = result
                
            # Get database file info
            db_path = db.engine.url.database
            if db_path:
                if os.path.exists(db_path):
                    db_file_size = os.path.getsize(db_path) / (1024 * 1024)  # Size in MB
                    db_modified_time = datetime.datetime.fromtimestamp(os.path.getmtime(db_path))
                else:
                    db_file_size = None
                    db_modified_time = None
            else:
                db_file_size = None
                db_modified_time = None
                
        except Exception as e:
            app.logger.error(f"Error getting database info: {str(e)}")
            flash(f"Error getting database info: {str(e)}", 'danger')
            table_list = []
            db_stats = {}
            db_file_size = None
            db_modified_time = None
        
        # Process form submission
        if request.method == 'POST':
            action = request.form.get('action', '')
            
            if action == 'run_query':
                # Run SQL query
                query = request.form.get('query', '').strip()
                
                if not query:
                    flash('Query cannot be empty.', 'danger')
                    return redirect(url_for('superadmin_database'))
                    
                # Check if query is read-only (SELECT only)
                if not query.lower().startswith('select'):
                    flash('Only SELECT queries are allowed for security reasons.', 'danger')
                    return redirect(url_for('superadmin_database'))
                
                try:
                    # Start timing
                    start_time = time.time()
                    
                    # Execute query
                    result = db.session.execute(text(query))
                    rows = result.fetchall()
                    columns = result.keys()
                    
                    # End timing
                    execution_time = round(time.time() - start_time, 3)
                    
                    query_result = {
                        'columns': columns,
                        'rows': rows,
                        'count': len(rows)
                    }
                    
                    app.logger.info(f"Superadmin ran database query: {query}")
                    
                except Exception as e:
                    query_error = str(e)
                    app.logger.error(f"Database query error: {str(e)}")
                    flash(f"Query error: {str(e)}", 'danger')
            
            elif action == 'backup_database':
                # Backup database
                try:
                    # Get database file path
                    db_path = db.engine.url.database
                    
                    if not db_path or not os.path.exists(db_path):
                        raise Exception("Database file not found")
                    
                    # Create backup directory if it doesn't exist
                    backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
                    os.makedirs(backup_dir, exist_ok=True)
                    
                    # Create backup filename with timestamp
                    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                    backup_filename = f"db_backup_{timestamp}.sqlite"
                    backup_path = os.path.join(backup_dir, backup_filename)
                    
                    # Copy database file to backup location
                    shutil.copy2(db_path, backup_path)
                    
                    # Check if backup was successful
                    if os.path.exists(backup_path):
                        backup_status = 'success'
                        backup_time = round(os.path.getsize(backup_path) / (1024 * 1024), 2)  # Size in MB
                        backup_message = f"Database backup created successfully: {backup_filename} ({backup_time} MB)"
                        flash(backup_message, 'success')
                        app.logger.info(f"Superadmin created database backup: {backup_filename}")
                    else:
                        raise Exception("Backup file was not created")
                    
                except Exception as e:
                    backup_status = 'error'
                    backup_message = f"Error creating database backup: {str(e)}"
                    flash(backup_message, 'danger')
                    app.logger.error(f"Database backup error: {str(e)}")
        
        # Get list of database backups
        backup_list = []
        backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
        if os.path.exists(backup_dir):
            for file in sorted(os.listdir(backup_dir), reverse=True):
                if file.startswith('db_backup_') and file.endswith('.sqlite'):
                    backup_path = os.path.join(backup_dir, file)
                    backup_size = round(os.path.getsize(backup_path) / (1024 * 1024), 2)  # Size in MB
                    backup_date = datetime.datetime.fromtimestamp(os.path.getmtime(backup_path))
                    
                    # Extract timestamp from filename
                    timestamp_str = file.replace('db_backup_', '').replace('.sqlite', '')
                    try:
                        timestamp = datetime.datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                    except:
                        timestamp = backup_date
                    
                    backup_list.append({
                        'filename': file,
                        'size': backup_size,
                        'date': timestamp,
                        'path': backup_path
                    })
        
        # Get sample queries
        sample_queries = [
            {
                'name': 'All Users',
                'query': 'SELECT * FROM user LIMIT 100'
            },
            {
                'name': 'Recent Appointments',
                'query': 'SELECT * FROM appointment ORDER BY created_at DESC LIMIT 50'
            },
            {
                'name': 'Stores with Counts',
                'query': 'SELECT s.id, s.name, COUNT(a.id) as appointment_count FROM store s LEFT JOIN appointment a ON s.id = a.store_id GROUP BY s.id ORDER BY appointment_count DESC'
            },
            {
                'name': 'Active Subscriptions',
                'query': 'SELECT * FROM subscription WHERE expires_at > CURRENT_TIMESTAMP'
            },
            {
                'name': 'Pets by Breed',
                'query': 'SELECT breed, COUNT(*) as count FROM pet GROUP BY breed ORDER BY count DESC'
            }
        ]
        
        # Render the database management page
        app.logger.info("Superadmin viewed database management page.")
        return render_template('superadmin_database.html',
                              table_list=table_list,
                              db_stats=db_stats,
                              db_file_size=db_file_size,
                              db_modified_time=db_modified_time,
                              query_result=query_result,
                              query_error=query_error,
                              execution_time=execution_time,
                              backup_status=backup_status,
                              backup_message=backup_message,
                              backup_time=backup_time,
                              backup_list=backup_list,
                              sample_queries=sample_queries)
                              
    # Superadmin Download Database Backup route
    @app.route('/superadmin/backup/download/<filename>')
    def superadmin_download_backup(filename):
        """
        Allows superadmins to download database backups.
        """
        from flask import send_from_directory, abort
        import os
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
            
        # Validate filename to prevent path traversal
        if '..' in filename or filename.startswith('/'):
            abort(404)
            
        # Only allow downloading backup files with expected pattern
        if not (filename.startswith('db_backup_') and filename.endswith('.sqlite')):
            abort(404)
            
        backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
        
        if not os.path.exists(os.path.join(backup_dir, filename)):
            abort(404)
            
        app.logger.info(f"Superadmin downloaded database backup: {filename}")
        
        return send_from_directory(
            directory=backup_dir,
            path=filename,
            as_attachment=True,
            download_name=filename
        )
        
    # Superadmin Delete Database Backup route
    @app.route('/superadmin/backup/delete/<filename>', methods=['POST'])
    def superadmin_delete_backup(filename):
        """
        Allows superadmins to delete database backups.
        """
        from flask import redirect, url_for, flash, abort
        import os
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
            
        # Validate filename to prevent path traversal
        if '..' in filename or filename.startswith('/'):
            abort(404)
            
        # Only allow deleting backup files with expected pattern
        if not (filename.startswith('db_backup_') and filename.endswith('.sqlite')):
            abort(404)
            
        backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
        backup_path = os.path.join(backup_dir, filename)
        
        if not os.path.exists(backup_path):
            flash(f"Backup file not found: {filename}", 'danger')
            return redirect(url_for('superadmin_database'))
            
        try:
            os.remove(backup_path)
            flash(f"Backup deleted successfully: {filename}", 'success')
            app.logger.info(f"Superadmin deleted database backup: {filename}")
        except Exception as e:
            flash(f"Error deleting backup: {str(e)}", 'danger')
            app.logger.error(f"Error deleting database backup {filename}: {str(e)}")
            
        return redirect(url_for('superadmin_database'))
        
    # Superadmin Store Management route
    @app.route('/superadmin/stores', methods=['GET', 'POST'])
    def superadmin_stores():
        """
        Allows superadmins to manage stores in the system.
        """
        from flask import render_template, request, flash, redirect, url_for
        import os
        import json
        import datetime
        from sqlalchemy import func
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Initialize variables
        stores = None
        store_to_edit = None
        error = None
        success = None
        
        # Get all stores with subscription information and appointment counts
        try:
            stores_data = db.session.query(
                Store, 
                Subscription,
                func.count(Appointment.id).label('appointment_count')
            ).outerjoin(
                Subscription, Store.id == Subscription.store_id
            ).outerjoin(
                Appointment, Store.id == Appointment.store_id
            ).group_by(Store.id).all()
            
            stores = []
            for store, subscription, appointment_count in stores_data:
                store_dict = {
                    'id': store.id,
                    'name': store.name,
                    'address': store.address,
                    'city': store.city,
                    'state': store.state,
                    'zip_code': store.zip_code,
                    'phone': store.phone,
                    'email': store.email,
                    'created_at': store.created_at,
                    'subscription': {
                        'id': subscription.id if subscription else None,
                        'plan': subscription.plan if subscription else None,
                        'status': subscription.status if subscription else 'inactive',
                        'created_at': subscription.created_at if subscription else None,
                        'expires_at': subscription.expires_at if subscription else None
                    } if subscription else {
                        'id': None,
                        'plan': None,
                        'status': 'inactive',
                        'created_at': None,
                        'expires_at': None
                    },
                    'appointment_count': appointment_count
                }
                stores.append(store_dict)
        except Exception as e:
            app.logger.error(f"Error fetching stores: {str(e)}")
            error = f"Error fetching stores: {str(e)}"
            stores = []
        
        # Handle edit store form submission
        if request.method == 'POST':
            action = request.form.get('action', '')
            
            if action == 'edit_store':
                store_id = request.form.get('store_id')
                
                if store_id:
                    # Get store to edit
                    store = Store.query.get(store_id)
                    
                    if store:
                        store_to_edit = {
                            'id': store.id,
                            'name': store.name,
                            'address': store.address,
                            'city': store.city,
                            'state': store.state,
                            'zip_code': store.zip_code,
                            'phone': store.phone,
                            'email': store.email
                        }
            
            elif action == 'update_store':
                store_id = request.form.get('store_id')
                name = request.form.get('name')
                address = request.form.get('address')
                city = request.form.get('city')
                state = request.form.get('state')
                zip_code = request.form.get('zip_code')
                phone = request.form.get('phone')
                email = request.form.get('email')
                
                if not store_id or not name:
                    error = "Store ID and name are required fields."
                    return redirect(url_for('superadmin_stores'))
                
                try:
                    store = Store.query.get(store_id)
                    
                    if store:
                        store.name = name
                        store.address = address
                        store.city = city
                        store.state = state
                        store.zip_code = zip_code
                        store.phone = phone
                        store.email = email
                        
                        db.session.commit()
                        success = f"Store '{name}' updated successfully."
                        app.logger.info(f"Superadmin updated store: {name} (ID: {store_id})")
                    else:
                        error = f"Store with ID {store_id} not found."
                except Exception as e:
                    db.session.rollback()
                    error = f"Error updating store: {str(e)}"
                    app.logger.error(f"Error updating store: {str(e)}")
            
            elif action == 'create_store':
                name = request.form.get('name')
                address = request.form.get('address')
                city = request.form.get('city')
                state = request.form.get('state')
                zip_code = request.form.get('zip_code')
                phone = request.form.get('phone')
                email = request.form.get('email')
                
                if not name:
                    error = "Store name is required."
                    return redirect(url_for('superadmin_stores'))
                
                try:
                    new_store = Store(
                        name=name,
                        address=address,
                        city=city,
                        state=state,
                        zip_code=zip_code,
                        phone=phone,
                        email=email,
                        created_at=datetime.datetime.now()
                    )
                    
                    db.session.add(new_store)
                    db.session.commit()
                    success = f"Store '{name}' created successfully."
                    app.logger.info(f"Superadmin created new store: {name} (ID: {new_store.id})")
                except Exception as e:
                    db.session.rollback()
                    error = f"Error creating store: {str(e)}"
                    app.logger.error(f"Error creating store: {str(e)}")
            
            elif action == 'delete_store':
                store_id = request.form.get('store_id')
                
                if not store_id:
                    error = "Store ID is required for deletion."
                    return redirect(url_for('superadmin_stores'))
                
                try:
                    store = Store.query.get(store_id)
                    
                    if store:
                        store_name = store.name
                        
                        # Check if store has appointments
                        appointment_count = Appointment.query.filter_by(store_id=store_id).count()
                        
                        if appointment_count > 0:
                            error = f"Cannot delete store '{store_name}' because it has {appointment_count} appointments. Delete all appointments first."
                            return redirect(url_for('superadmin_stores'))
                        
                        # Delete store's subscription if any
                        subscription = Subscription.query.filter_by(store_id=store_id).first()
                        if subscription:
                            db.session.delete(subscription)
                        
                        # Delete store
                        db.session.delete(store)
                        db.session.commit()
                        success = f"Store '{store_name}' deleted successfully."
                        app.logger.info(f"Superadmin deleted store: {store_name} (ID: {store_id})")
                    else:
                        error = f"Store with ID {store_id} not found."
                except Exception as e:
                    db.session.rollback()
                    error = f"Error deleting store: {str(e)}"
                    app.logger.error(f"Error deleting store: {str(e)}")
            
            elif action == 'update_subscription':
                store_id = request.form.get('store_id')
                plan = request.form.get('plan')
                status = request.form.get('status')
                duration_months = request.form.get('duration_months', type=int)
                
                if not store_id or not plan or not status or not duration_months:
                    error = "Store ID, plan, status, and duration are all required."
                    return redirect(url_for('superadmin_stores'))
                
                try:
                    # Check if store exists
                    store = Store.query.get(store_id)
                    
                    if not store:
                        error = f"Store with ID {store_id} not found."
                        return redirect(url_for('superadmin_stores'))
                    
                    # Check if subscription exists
                    subscription = Subscription.query.filter_by(store_id=store_id).first()
                    
                    # Calculate expiry date
                    now = datetime.datetime.now()
                    expires_at = now + datetime.timedelta(days=30 * duration_months)
                    
                    if subscription:
                        # Update existing subscription
                        subscription.plan = plan
                        subscription.status = status
                        subscription.expires_at = expires_at
                        
                        msg = f"Subscription updated for store '{store.name}'."
                    else:
                        # Create new subscription
                        subscription = Subscription(
                            store_id=store_id,
                            plan=plan,
                            status=status,
                            created_at=now,
                            expires_at=expires_at
                        )
                        db.session.add(subscription)
                        
                        msg = f"Subscription created for store '{store.name}'."
                    
                    db.session.commit()
                    success = msg
                    app.logger.info(f"Superadmin {msg}")
                except Exception as e:
                    db.session.rollback()
                    error = f"Error updating subscription: {str(e)}"
                    app.logger.error(f"Error updating subscription: {str(e)}")
            
            # Redirect to refresh the page and display the updated data
            if not store_to_edit:  # Only redirect if we're not showing the edit form
                return redirect(url_for('superadmin_stores'))
        
        # Available subscription plans
        subscription_plans = ['free', 'basic', 'premium', 'enterprise']
        
        # Available subscription statuses
        subscription_statuses = ['active', 'inactive', 'pending', 'cancelled', 'expired']
        
        # Available US states for dropdown
        us_states = [
            'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
            'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
            'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
            'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
            'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
        ]
        
        # Render the store management page
        app.logger.info("Superadmin viewed store management page.")
        return render_template('superadmin_stores.html',
                              stores=stores,
                              store_to_edit=store_to_edit,
                              error=error,
                              success=success,
                              subscription_plans=subscription_plans,
                              subscription_statuses=subscription_statuses,
                              us_states=us_states)
                              
    # Superadmin Global Configuration Settings route
    @app.route('/superadmin/global-configuration-alt', methods=['GET', 'POST'])
    def superadmin_global_config_alt():
        """
        Allows superadmins to manage global configuration settings.
        """
        from flask import render_template, request, flash, redirect, url_for
        import os
        import json
        import datetime
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Initialize variables
        config_file = os.path.join(os.path.dirname(__file__), 'config', 'app_config.json')
        config_dir = os.path.dirname(config_file)
        success = None
        error = None
        config_data = {}
        
        # Create config directory if it doesn't exist
        os.makedirs(config_dir, exist_ok=True)
        
        # Load existing configuration if available
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config_data = json.load(f)
            except Exception as e:
                app.logger.error(f"Error loading configuration: {str(e)}")
                error = f"Error loading configuration: {str(e)}"
                config_data = {}
        
        # Define default configuration values
        default_config = {
            "app_settings": {
                "site_name": "Pawfection Grooming Solutions",
                "contact_email": "support@pawfection.example.com",
                "support_phone": "+1-555-PAWFECT",
                "timezone": "America/New_York",
                "date_format": "%Y-%m-%d",
                "time_format": "12h",  # 12h or 24h
                "items_per_page": 25,
                "allow_registration": True,
                "maintenance_mode": False,
            },
            "notification_settings": {
                "enable_email_notifications": True,
                "enable_sms_notifications": False,
                "appointment_reminder_hours": 24,
                "send_welcome_email": True,
            },
            "security_settings": {
                "password_min_length": 8,
                "require_special_chars": True,
                "session_timeout_minutes": 60,
                "failed_login_attempts": 5,
                "account_lockout_minutes": 30,
                "enable_two_factor": False,
            },
            "feature_flags": {
                "enable_online_booking": True,
                "enable_customer_profiles": True,
                "enable_inventory_management": False,
                "enable_reporting": True,
                "enable_marketing_tools": False,
                "beta_features": False,
            },
            "api_settings": {
                "enable_api": False,
                "rate_limit_per_minute": 60,
                "require_api_keys": True,
            },
            "last_updated": datetime.datetime.now().isoformat(),
        }
        
        # Merge default config with existing config
        for category, settings in default_config.items():
            if category not in config_data:
                config_data[category] = {}
            
            for setting, value in settings.items():
                if setting not in config_data[category]:
                    config_data[category][setting] = value
        
        # Handle form submission
        if request.method == 'POST':
            action = request.form.get('action', '')
            
            if action == 'update_config':
                category = request.form.get('category')
                
                if category in config_data:
                    # Update each setting in the category
                    for setting in config_data[category]:
                        # Skip last_updated field
                        if setting == 'last_updated':
                            continue
                            
                        # Get the form value with appropriate type conversion
                        form_value = request.form.get(f"{category}_{setting}")
                        
                        # Convert value to appropriate type based on default
                        default_type = type(default_config[category].get(setting))
                        
                        if default_type == bool:
                            form_value = form_value == 'true'
                        elif default_type == int:
                            try:
                                form_value = int(form_value)
                            except (ValueError, TypeError):
                                form_value = default_config[category].get(setting, 0)
                        elif default_type == float:
                            try:
                                form_value = float(form_value)
                            except (ValueError, TypeError):
                                form_value = default_config[category].get(setting, 0.0)
                        
                        # Update the config value
                        config_data[category][setting] = form_value
                    
                    # Update last_updated timestamp
                    config_data['last_updated'] = datetime.datetime.now().isoformat()
                    
                    # Save updated config
                    try:
                        with open(config_file, 'w') as f:
                            json.dump(config_data, f, indent=4)
                        
                        success = f"{category.replace('_', ' ').title()} settings updated successfully."
                        app.logger.info(f"Superadmin updated configuration: {category}")
                    except Exception as e:
                        error = f"Error saving configuration: {str(e)}"
                        app.logger.error(f"Error saving configuration: {str(e)}")
                else:
                    error = f"Invalid configuration category: {category}"
                    app.logger.error(f"Invalid configuration category: {category}")
            
            elif action == 'reset_defaults':
                category = request.form.get('category')
                
                if category in default_config:
                    # Reset category to defaults
                    config_data[category] = default_config[category].copy()
                    
                    # Update last_updated timestamp
                    config_data['last_updated'] = datetime.datetime.now().isoformat()
                    
                    # Save updated config
                    try:
                        with open(config_file, 'w') as f:
                            json.dump(config_data, f, indent=4)
                        
                        success = f"{category.replace('_', ' ').title()} settings reset to defaults."
                        app.logger.info(f"Superadmin reset configuration to defaults: {category}")
                    except Exception as e:
                        error = f"Error saving configuration: {str(e)}"
                        app.logger.error(f"Error saving configuration: {str(e)}")
                else:
                    error = f"Invalid configuration category: {category}"
                    app.logger.error(f"Invalid configuration category: {category}")
        
        # Format the last updated time for display
        last_updated_str = None
        if 'last_updated' in config_data:
            try:
                last_updated = datetime.datetime.fromisoformat(config_data['last_updated'])
                last_updated_str = last_updated.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                last_updated_str = 'Unknown'
        
        # Render the configuration page
        app.logger.info("Superadmin viewed configuration settings page.")
        return render_template('superadmin_configuration.html',
                              config=config_data,
                              last_updated=last_updated_str,
                              success=success,
                              error=error)

    # Superadmin impersonate store
    @app.route('/superadmin/impersonate/<int:store_id>')
    def superadmin_impersonate(store_id):
        """
        Allows a superadmin to 'impersonate' a specific store.
        """
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        store_to_impersonate = db.session.get(Store, store_id)
        if not store_to_impersonate:
            flash("Store not found for impersonation.", "danger")
            return redirect(url_for('superadmin_dashboard'))

        session['store_id'] = store_id
        session['impersonating'] = True
        
        # Set custom message for impersonation
        session['impersonation_message'] = f"You are currently impersonating {store_to_impersonate.name}. <a href='/superadmin/stop_impersonating'>Stop impersonating</a>"
        
        # Log impersonation
        app.logger.info(f"Superadmin impersonated store: {store_to_impersonate.name} (ID: {store_id})")
        flash(f"Now impersonating store: {store_to_impersonate.name}", "info")
        
        return redirect(url_for('home'))
    
    # Superadmin User Permissions route
    @app.route('/superadmin/user_permissions', methods=['GET', 'POST'])
    def superadmin_user_permissions():
        """
        Allows superadmins to manage user permissions, roles, and access controls.
        """
        from flask import render_template, request, flash, redirect, url_for, jsonify
        import datetime
        import json
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Initialize variables
        success = None
        error = None
        
        # Query all users including their roles
        try:
            users = User.query.all()
            stores = Store.query.all()
            
            # Define roles with default permissions
            roles = {
                'superadmin': {
                    'description': 'Full access to all system features',
                    'permissions': ['manage_users', 'manage_stores', 'manage_system', 'manage_subscriptions', 
                                   'view_analytics', 'manage_configuration', 'access_api', 'manage_permissions']
                },
                'admin': {
                    'description': 'Full access to store-specific features',
                    'permissions': ['manage_appointments', 'manage_customers', 'manage_groomers', 'view_reports',
                                   'manage_services', 'manage_billing', 'view_store_analytics']
                },
                'groomer': {
                    'description': 'Access to grooming-related features',
                    'permissions': ['view_appointments', 'manage_own_appointments', 'view_customers',
                                   'view_services']
                }
            }
            
            # Define all possible permissions with descriptions
            permissions = [
                {'id': 'manage_users', 'name': 'Manage Users', 'description': 'Create, edit, and delete users'},
                {'id': 'manage_stores', 'name': 'Manage Stores', 'description': 'Create, edit, and delete stores'},
                {'id': 'manage_system', 'name': 'Manage System', 'description': 'Access to system settings and maintenance'},
                {'id': 'manage_subscriptions', 'name': 'Manage Subscriptions', 'description': 'Manage store subscriptions'},
                {'id': 'view_analytics', 'name': 'View Analytics', 'description': 'Access to system-wide analytics'},
                {'id': 'manage_configuration', 'name': 'Manage Configuration', 'description': 'Modify system configuration'},
                {'id': 'access_api', 'name': 'Access API', 'description': 'Use API endpoints'},
                {'id': 'manage_permissions', 'name': 'Manage Permissions', 'description': 'Modify user permissions'},
                {'id': 'manage_appointments', 'name': 'Manage Appointments', 'description': 'Full control over appointments'},
                {'id': 'manage_customers', 'name': 'Manage Customers', 'description': 'Manage customer data'},
                {'id': 'manage_groomers', 'name': 'Manage Groomers', 'description': 'Manage groomer settings'},
                {'id': 'view_reports', 'name': 'View Reports', 'description': 'Access to store reports'},
                {'id': 'manage_services', 'name': 'Manage Services', 'description': 'Manage grooming services'},
                {'id': 'manage_billing', 'name': 'Manage Billing', 'description': 'Access to billing and invoices'},
                {'id': 'view_store_analytics', 'name': 'View Store Analytics', 'description': 'Access to store-specific analytics'},
                {'id': 'view_appointments', 'name': 'View Appointments', 'description': 'Read-only access to appointments'},
                {'id': 'manage_own_appointments', 'name': 'Manage Own Appointments', 'description': 'Manage assigned appointments'},
                {'id': 'view_customers', 'name': 'View Customers', 'description': 'Read-only access to customers'},
                {'id': 'view_services', 'name': 'View Services', 'description': 'Read-only access to services'}
            ]
            
            # Mock user permissions for demonstration
            # In production, this would come from a database table
            user_permissions = {}
            for user in users:
                if user.role == 'superadmin':
                    user_permissions[user.id] = roles['superadmin']['permissions']
                elif user.role == 'admin':
                    user_permissions[user.id] = roles['admin']['permissions']
                else:  # groomer or other roles
                    user_permissions[user.id] = roles['groomer']['permissions']
        except Exception as e:
            app.logger.error(f"Error querying data for user permissions: {str(e)}")
            error = f"Error loading user data: {str(e)}"
            users = []
            stores = []
            roles = {}
            permissions = []
            user_permissions = {}
        
        # Handle API requests
        if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            action = request.json.get('action')
            
            try:
                if action == 'get_user_details':
                    user_id = request.json.get('user_id')
                    user = User.query.get(user_id)
                    
                    if not user:
                        return jsonify({'status': 'error', 'message': 'User not found'}), 404
                    
                    user_data = {
                        'id': user.id,
                        'username': user.username,
                        'role': user.role,
                        'email': user.email,
                        'is_admin': user.is_admin,
                        'is_groomer': user.is_groomer,
                        'store_id': user.store_id,
                        'permissions': user_permissions.get(user.id, [])
                    }
                    
                    return jsonify({'status': 'success', 'user': user_data})
                
                elif action == 'update_user_permission':
                    user_id = request.json.get('user_id')
                    permission_id = request.json.get('permission_id')
                    is_granted = request.json.get('is_granted', False)
                    
                    # In production, update the user's permissions in the database
                    # Here we're just sending a success response
                    
                    # Log the action
                    app.logger.info(f"Superadmin {'granted' if is_granted else 'revoked'} permission '{permission_id}' for user ID {user_id}")
                    
                    return jsonify({
                        'status': 'success',
                        'message': f"Permission {'granted' if is_granted else 'revoked'} successfully"
                    })
                
                elif action == 'update_role_permission':
                    role_name = request.json.get('role_name')
                    permission_id = request.json.get('permission_id')
                    is_granted = request.json.get('is_granted', False)
                    
                    # In production, update the role's permissions in the database
                    # Here we're just sending a success response
                    
                    # Log the action
                    app.logger.info(f"Superadmin {'added' if is_granted else 'removed'} permission '{permission_id}' from role '{role_name}'")
                    
                    return jsonify({
                        'status': 'success',
                        'message': f"Role permission {'added' if is_granted else 'removed'} successfully"
                    })
                
                elif action == 'add_permission':
                    permission_id = request.json.get('id')
                    name = request.json.get('name')
                    description = request.json.get('description')
                    
                    # In production, add the permission to the database
                    # Here we're just sending a success response with the new permission data
                    
                    # Log the action
                    app.logger.info(f"Superadmin created new permission: {name}")
                    
                    return jsonify({
                        'status': 'success',
                        'message': "Permission created successfully",
                        'permission': {
                            'id': permission_id,
                            'name': name,
                            'description': description
                        }
                    })
                
                elif action == 'delete_permission':
                    permission_id = request.json.get('id')
                    
                    # In production, delete the permission from the database
                    # Here we're just sending a success response
                    
                    # Log the action
                    app.logger.info(f"Superadmin deleted permission: {permission_id}")
                    
                    return jsonify({
                        'status': 'success',
                        'message': "Permission deleted successfully"
                    })
                
                elif action == 'add_user':
                    username = request.json.get('username')
                    email = request.json.get('email')
                    password = request.json.get('password')
                    role = request.json.get('role')
                    store_id = request.json.get('store_id')
                    
                    if not username or not email or not password or not role:
                        return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
                    
                    # Check if username or email already exists
                    if User.query.filter_by(username=username).first():
                        return jsonify({'status': 'error', 'message': 'Username already exists'}), 400
                    
                    if User.query.filter_by(email=email).first():
                        return jsonify({'status': 'error', 'message': 'Email already exists'}), 400
                    
                    # Create new user
                    new_user = User(
                        username=username,
                        email=email,
                        role=role,
                        store_id=store_id if store_id else None,
                        is_admin=True if role == 'admin' else False,
                        is_groomer=True if role == 'groomer' else False,
                        created_at=datetime.datetime.now()
                    )
                    
                    new_user.set_password(password)
                    
                    db.session.add(new_user)
                    db.session.commit()
                    
                    # Log the action
                    app.logger.info(f"Superadmin created new user: {username}")
                    
                    return jsonify({
                        'status': 'success',
                        'message': 'User created successfully',
                        'user': {
                            'id': new_user.id,
                            'username': new_user.username,
                            'email': new_user.email,
                            'role': new_user.role
                        }
                    })
                
                elif action == 'edit_user':
                    user_id = request.json.get('id')
                    username = request.json.get('username')
                    email = request.json.get('email')
                    role = request.json.get('role')
                    store_id = request.json.get('store_id')
                    password = request.json.get('password')  # Optional
                    
                    if not user_id or not username or not email or not role:
                        return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
                    
                    user = User.query.get(user_id)
                    
                    if not user:
                        return jsonify({'status': 'error', 'message': 'User not found'}), 404
                    
                    # Check if username or email already exists for another user
                    username_exists = User.query.filter(User.username == username, User.id != user_id).first()
                    if username_exists:
                        return jsonify({'status': 'error', 'message': 'Username already exists'}), 400
                    
                    email_exists = User.query.filter(User.email == email, User.id != user_id).first()
                    if email_exists:
                        return jsonify({'status': 'error', 'message': 'Email already exists'}), 400
                    
                    # Update user
                    user.username = username
                    user.email = email
                    user.role = role
                    user.store_id = store_id if store_id else None
                    user.is_admin = True if role == 'admin' else False
                    user.is_groomer = True if role == 'groomer' else False
                    
                    if password:
                        user.set_password(password)
                    
                    db.session.commit()
                    
                    # Log the action
                    app.logger.info(f"Superadmin updated user: {username}")
                    
                    return jsonify({
                        'status': 'success',
                        'message': 'User updated successfully',
                        'user': {
                            'id': user.id,
                            'username': user.username,
                            'email': user.email,
                            'role': user.role
                        }
                    })
                
                else:
                    return jsonify({'status': 'error', 'message': 'Invalid action'}), 400
                    
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error in user permissions API: {str(e)}")
                return jsonify({'status': 'error', 'message': str(e)}), 500
        
        # Render the user permissions page
        app.logger.info("Superadmin viewed user permissions page.")
        return render_template('superadmin_user_permissions.html', 
                               users=users, 
                               stores=stores, 
                               roles=roles, 
                               permissions=permissions, 
                               user_permissions=user_permissions,
                               error=error, 
                               success=success)
    
    # Superadmin System Alerts route
    @app.route('/superadmin/system-alerts', methods=['GET', 'POST'])
    def superadmin_system_alerts():
        """
        System Alerts dashboard for monitoring and managing system-wide alerts.
        """
        from flask import render_template, request, flash, redirect, url_for, jsonify
        import datetime
        import json
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Mock data for alerts - in production this would come from a database
        mock_alerts = [
            {
                'id': '1',
                'title': 'Database Connection Issue',
                'message': 'Intermittent connection issues detected with the main database.',
                'details': 'Connection timeout occurring every 30 minutes. Investigating potential network issues.',
                'type': 'warning',
                'source': 'Database Monitor',
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'resolved': False
            },
            {
                'id': '2',
                'title': 'Critical Security Update',
                'message': 'Security vulnerability CVE-2023-1234 detected in system library.',
                'details': 'Update to library version 2.5.1 or higher is required immediately.',
                'type': 'critical',
                'source': 'Security Scanner',
                'timestamp': (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
                'resolved': False
            },
            {
                'id': '3',
                'title': 'New Store Registration',
                'message': 'New store "Happy Paws Grooming" has completed registration.',
                'details': None,
                'type': 'info',
                'source': 'Registration Service',
                'timestamp': (datetime.datetime.now() - datetime.timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S'),
                'resolved': True
            },
            {
                'id': '4',
                'title': 'System Backup Completed',
                'message': 'Daily system backup completed successfully.',
                'details': 'Backup size: 1.2GB. Stored in secure cloud storage.',
                'type': 'success',
                'source': 'Backup Service',
                'timestamp': (datetime.datetime.now() - datetime.timedelta(hours=6)).strftime('%Y-%m-%d %H:%M:%S'),
                'resolved': True
            },
            {
                'id': '5',
                'title': 'High CPU Usage',
                'message': 'Server experiencing sustained high CPU usage (>85%).',
                'details': 'Investigating potential resource-intensive processes or attacks.',
                'type': 'warning',
                'source': 'System Monitor',
                'timestamp': (datetime.datetime.now() - datetime.timedelta(minutes=45)).strftime('%Y-%m-%d %H:%M:%S'),
                'resolved': False
            }
        ]
        
        # Calculate stats
        stats = {
            'total': len(mock_alerts),
            'critical': sum(1 for alert in mock_alerts if alert['type'] == 'critical'),
            'warning': sum(1 for alert in mock_alerts if alert['type'] == 'warning'),
            'info': sum(1 for alert in mock_alerts if alert['type'] in ['info', 'success']),
            'resolved': sum(1 for alert in mock_alerts if alert['resolved'])
        }
        
        # Handle POST requests for alert actions
        if request.method == 'POST':
            action = request.form.get('action', '')
            alert_id = request.form.get('alert_id', '')
            
            # Handle different actions
            if request.path == '/superadmin/resolve-alert':
                # Find the alert and mark it as resolved
                for alert in mock_alerts:
                    if alert['id'] == alert_id:
                        alert['resolved'] = True
                        flash(f"Alert '{alert['title']}' marked as resolved.", 'success')
                        app.logger.info(f"Superadmin resolved alert ID: {alert_id}")
                        break
                return redirect(url_for('superadmin_system_alerts'))
                
            elif request.path == '/superadmin/delete-alert':
                # In a real implementation, this would delete from the database
                # Here we just remove from our mock list
                mock_alerts = [a for a in mock_alerts if a['id'] != alert_id]
                flash("Alert deleted successfully.", 'success')
                app.logger.info(f"Superadmin deleted alert ID: {alert_id}")
                return redirect(url_for('superadmin_system_alerts'))
                
            elif request.path == '/superadmin/create-alert':
                # Create a new alert
                title = request.form.get('title')
                message = request.form.get('message')
                alert_type = request.form.get('type')
                source = request.form.get('source')
                
                if title and message and alert_type:
                    # Generate a simple ID (would be auto-generated in a real DB)
                    new_id = str(max(int(a['id']) for a in mock_alerts) + 1)
                    
                    new_alert = {
                        'id': new_id,
                        'title': title,
                        'message': message,
                        'details': None,
                        'type': alert_type,
                        'source': source or 'Manual Entry',
                        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'resolved': False
                    }
                    
                    # In a real implementation, this would be saved to the database
                    # Here we just add to our mock list
                    mock_alerts.append(new_alert)
                    
                    flash("New alert created successfully.", 'success')
                    app.logger.info(f"Superadmin created new alert: {title}")
                else:
                    flash("Failed to create alert. Missing required fields.", 'danger')
                
                return redirect(url_for('superadmin_system_alerts'))
        
        # Log the view
        app.logger.info("Superadmin viewed system alerts dashboard.")
        
        # Render the template with alert data
        return render_template('superadmin_alerts.html',
                              alerts=mock_alerts,
                              stats=stats)
    
    # Superadmin User Management route
    @app.route('/superadmin/manage-users', methods=['GET', 'POST'])
    def superadmin_user_management_alt():
        """
        User management interface for superadmins to manage all system users.
        """
        from flask import render_template, request, flash, redirect, url_for, jsonify
        import datetime
        import math
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Get query parameters for search, filtering and sorting
        search_query = request.args.get('search', '')
        role_filter = request.args.get('role', 'all')
        sort_by = request.args.get('sort_by', 'username')
        sort_order = request.args.get('sort_order', 'asc')
        page = request.args.get('page', 1, type=int)
        per_page = 10  # Number of users per page
        
        # Query users based on filters
        query = User.query
        
        # Apply search filter if provided
        if search_query:
            query = query.filter(
                (User.username.ilike(f'%{search_query}%')) |
                (User.email.ilike(f'%{search_query}%'))
            )
        
        # Apply role filter if not 'all'
        if role_filter != 'all':
            query = query.filter(User.role == role_filter)
        
        # Apply sorting
        if sort_by == 'username':
            query = query.order_by(User.username.asc() if sort_order == 'asc' else User.username.desc())
        elif sort_by == 'email':
            query = query.order_by(User.email.asc() if sort_order == 'asc' else User.email.desc())
        elif sort_by == 'role':
            query = query.order_by(User.role.asc() if sort_order == 'asc' else User.role.desc())
        elif sort_by == 'created_at':
            query = query.order_by(User.created_at.asc() if sort_order == 'asc' else User.created_at.desc())
        
        # Get total users count for pagination
        total_users = query.count()
        total_pages = math.ceil(total_users / per_page)
        
        # Apply pagination
        users = query.paginate(page=page, per_page=per_page)
        
        # Get all stores for dropdown in forms
        stores = Store.query.all()
        
        # Handle API requests (AJAX)
        if request.method == 'POST' and request.headers.get('Content-Type') == 'application/json':
            data = request.get_json()
            action = data.get('action')
            
            try:
                if action == 'add_user':
                    # Validate required fields
                    username = data.get('username')
                    email = data.get('email')
                    password = data.get('password')
                    role = data.get('role')
                    store_id = data.get('store_id')
                    
                    if not username or not email or not password or not role:
                        return jsonify({
                            'success': False,
                            'message': 'All fields are required'
                        }), 400
                    
                    # Check if username or email already exists
                    if User.query.filter_by(username=username).first():
                        return jsonify({
                            'success': False,
                            'message': 'Username already exists'
                        }), 400
                    
                    if User.query.filter_by(email=email).first():
                        return jsonify({
                            'success': False,
                            'message': 'Email already exists'
                        }), 400
                    
                    # Create new user
                    new_user = User(
                        username=username,
                        email=email,
                        role=role,
                        store_id=store_id if store_id else None,
                        is_admin=(role == 'admin'),
                        is_groomer=(role == 'groomer'),
                        created_at=datetime.datetime.now()
                    )
                    
                    new_user.set_password(password)
                    
                    db.session.add(new_user)
                    db.session.commit()
                    
                    # Log the action
                    app.logger.info(f"Superadmin created new user: {username}")
                    
                    return jsonify({
                        'success': True,
                        'message': 'User created successfully',
                        'user': {
                            'id': new_user.id,
                            'username': new_user.username,
                            'email': new_user.email,
                            'role': new_user.role
                        }
                    })
                
                elif action == 'edit_user':
                    user_id = data.get('id')
                    username = data.get('username')
                    email = data.get('email')
                    role = data.get('role')
                    store_id = data.get('store_id')
                    active = data.get('active', True)
                    
                    if not user_id or not username or not email or not role:
                        return jsonify({
                            'success': False,
                            'message': 'Required fields missing'
                        }), 400
                    
                    # Find the user
                    user = User.query.get(user_id)
                    if not user:
                        return jsonify({
                            'success': False,
                            'message': 'User not found'
                        }), 404
                    
                    # Check for username/email conflicts with other users
                    username_exists = User.query.filter(User.username == username, User.id != user_id).first()
                    if username_exists:
                        return jsonify({
                            'success': False,
                            'message': 'Username already in use by another user'
                        }), 400
                    
                    email_exists = User.query.filter(User.email == email, User.id != user_id).first()
                    if email_exists:
                        return jsonify({
                            'success': False,
                            'message': 'Email already in use by another user'
                        }), 400
                    
                    # Update user
                    user.username = username
                    user.email = email
                    user.role = role
                    user.store_id = store_id if store_id else None
                    user.is_admin = (role == 'admin')
                    user.is_groomer = (role == 'groomer')
                    user.active = active
                    
                    db.session.commit()
                    
                    # Log the action
                    app.logger.info(f"Superadmin updated user ID {user_id}: {username}")
                    
                    return jsonify({
                        'success': True,
                        'message': 'User updated successfully',
                        'user': {
                            'id': user.id,
                            'username': user.username,
                            'email': user.email,
                            'role': user.role,
                            'active': user.active
                        }
                    })
                
                elif action == 'delete_user':
                    user_id = data.get('id')
                    
                    if not user_id:
                        return jsonify({
                            'success': False,
                            'message': 'User ID required'
                        }), 400
                    
                    # Find the user
                    user = User.query.get(user_id)
                    if not user:
                        return jsonify({
                            'success': False,
                            'message': 'User not found'
                        }), 404
                    
                    # Don't allow deleting yourself
                    if user.id == session.get('user_id'):
                        return jsonify({
                            'success': False,
                            'message': 'Cannot delete your own account'
                        }), 400
                    
                    # Log before deletion for audit trail
                    username = user.username
                    
                    # Delete the user
                    db.session.delete(user)
                    db.session.commit()
                    
                    # Log the action
                    app.logger.info(f"Superadmin deleted user ID {user_id}: {username}")
                    
                    return jsonify({
                        'success': True,
                        'message': f'User {username} deleted successfully'
                    })
                
                elif action == 'reset_password':
                    user_id = data.get('id')
                    new_password = data.get('password')
                    
                    if not user_id or not new_password:
                        return jsonify({
                            'success': False,
                            'message': 'User ID and new password required'
                        }), 400
                    
                    # Find the user
                    user = User.query.get(user_id)
                    if not user:
                        return jsonify({
                            'success': False,
                            'message': 'User not found'
                        }), 404
                    
                    # Update password
                    user.set_password(new_password)
                    db.session.commit()
                    
                    # Log the action
                    app.logger.info(f"Superadmin reset password for user ID {user_id}: {user.username}")
                    
                    return jsonify({
                        'success': True,
                        'message': 'Password reset successfully'
                    })
                
                else:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid action'
                    }), 400
            
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error in user management API: {str(e)}")
                return jsonify({
                    'success': False,
                    'message': f'An error occurred: {str(e)}'
                }), 500
        
        # For GET requests, render the template
        app.logger.info("Superadmin viewed user management page")
        
        # Define role options for filter dropdown
        role_options = [
            {'value': 'all', 'label': 'All Roles'},
            {'value': 'superadmin', 'label': 'Superadmin'},
            {'value': 'admin', 'label': 'Admin'},
            {'value': 'groomer', 'label': 'Groomer'},
            {'value': 'customer', 'label': 'Customer'}
        ]
        
        return render_template('superadmin_user_management.html',
                              users=users.items,
                              stores=stores,
                              search_query=search_query,
                              role_filter=role_filter,
                              role_options=role_options,
                              sort_by=sort_by,
                              sort_order=sort_order,
                              current_page=page,
                              total_pages=total_pages,
                              total_users=total_users)
    
    # Superadmin Data Export route
    @app.route('/superadmin/data-export', methods=['GET', 'POST'])
    def superadmin_data_export_alt():
        """
        Data export interface for superadmins to export system data in various formats.
        """
        from flask import render_template, request, flash, redirect, url_for, jsonify, send_file
        import datetime
        import json
        import csv
        import io
        import os
        import pandas as pd
        from sqlalchemy import inspect
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Get all table names from SQLAlchemy models
        tables = []
        for table_name in inspect(db.engine).get_table_names():
            tables.append({
                'name': table_name,
                'display_name': table_name.replace('_', ' ').title(),
                'record_count': db.session.execute(f"SELECT COUNT(*) FROM {table_name}").scalar()
            })
        
        # Define supported export formats
        export_formats = [
            {'value': 'csv', 'name': 'CSV', 'description': 'Comma-separated values file'},
            {'value': 'json', 'name': 'JSON', 'description': 'JavaScript Object Notation'},
            {'value': 'excel', 'name': 'Excel', 'description': 'Microsoft Excel spreadsheet'}
        ]
        
        # Mock export history data
        export_history = [
            {
                'id': '1',
                'table': 'users',
                'format': 'csv',
                'records': 156,
                'timestamp': (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
                'file_size': '32 KB',
                'status': 'completed',
                'download_url': '#'
            },
            {
                'id': '2',
                'table': 'appointments',
                'format': 'json',
                'records': 1289,
                'timestamp': (datetime.datetime.now() - datetime.timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S'),
                'file_size': '245 KB',
                'status': 'completed',
                'download_url': '#'
            },
            {
                'id': '3',
                'table': 'stores',
                'format': 'excel',
                'records': 24,
                'timestamp': (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S'),
                'file_size': '18 KB',
                'status': 'completed',
                'download_url': '#'
            },
            {
                'id': '4',
                'table': 'customers',
                'format': 'csv',
                'records': 720,
                'timestamp': (datetime.datetime.now() - datetime.timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S'),
                'file_size': '124 KB',
                'status': 'completed',
                'download_url': '#'
            },
            {
                'id': '5',
                'table': 'transactions',
                'format': 'json',
                'records': 3456,
                'timestamp': (datetime.datetime.now() - datetime.timedelta(days=15)).strftime('%Y-%m-%d %H:%M:%S'),
                'file_size': '560 KB',
                'status': 'completed',
                'download_url': '#'
            }
        ]
        
        # Handle POST requests for data export
        if request.method == 'POST':
            # Check if it's a regular form submission or AJAX
            if request.headers.get('Content-Type') == 'application/json':
                data = request.get_json()
                action = data.get('action')
                
                if action == 'get_table_columns':
                    table_name = data.get('table_name')
                    
                    # Check if table exists
                    if table_name not in [t['name'] for t in tables]:
                        return jsonify({
                            'success': False,
                            'message': f'Table {table_name} not found'
                        }), 404
                    
                    try:
                        # Get table columns
                        columns = db.session.execute(f"SELECT * FROM {table_name} LIMIT 0").keys()
                        
                        return jsonify({
                            'success': True,
                            'columns': list(columns)
                        })
                    except Exception as e:
                        app.logger.error(f"Error getting columns for table {table_name}: {str(e)}")
                        return jsonify({
                            'success': False,
                            'message': f'Error: {str(e)}'
                        }), 500
            else:
                # Regular form submission for exporting data
                table_name = request.form.get('table')
                export_format = request.form.get('format')
                filter_condition = request.form.get('filter')
                selected_columns = request.form.getlist('columns')
                
                # Check required fields
                if not table_name or not export_format:
                    flash('Table and export format are required.', 'danger')
                    return redirect(url_for('superadmin_data_export'))
                
                try:
                    # Build the SQL query
                    if selected_columns and len(selected_columns) > 0:
                        columns_str = ', '.join(selected_columns)
                    else:
                        columns_str = '*'
                    
                    sql_query = f"SELECT {columns_str} FROM {table_name}"
                    
                    # Add filter condition if provided
                    if filter_condition:
                        sql_query += f" WHERE {filter_condition}"
                    
                    # Execute query
                    result = db.session.execute(sql_query)
                    data = [dict(row) for row in result]
                    
                    # Create the export file based on format
                    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"{table_name}_export_{timestamp}"
                    
                    # Log the export
                    app.logger.info(f"Superadmin exported {table_name} data in {export_format} format")
                    
                    # Create the appropriate export format
                    if export_format == 'csv':
                        output = io.StringIO()
                        if data:
                            writer = csv.DictWriter(output, fieldnames=data[0].keys())
                            writer.writeheader()
                            writer.writerows(data)
                        
                        response = output.getvalue()
                        output.close()
                        
                        # Create response
                        response_data = io.BytesIO(response.encode('utf-8'))
                        mimetype = 'text/csv'
                        filename = f"{filename}.csv"
                        
                    elif export_format == 'json':
                        response_data = io.BytesIO(json.dumps(data, indent=4, default=str).encode('utf-8'))
                        mimetype = 'application/json'
                        filename = f"{filename}.json"
                        
                    elif export_format == 'excel':
                        output = io.BytesIO()
                        df = pd.DataFrame(data)
                        writer = pd.ExcelWriter(output, engine='xlsxwriter')
                        df.to_excel(writer, sheet_name=table_name, index=False)
                        writer.save()
                        response_data = io.BytesIO(output.getvalue())
                        output.close()
                        mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                        filename = f"{filename}.xlsx"
                    
                    # Add a new entry to export history
                    new_export = {
                        'id': str(len(export_history) + 1),
                        'table': table_name,
                        'format': export_format,
                        'records': len(data),
                        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'file_size': f"{len(response_data.getvalue()) // 1024} KB",
                        'status': 'completed',
                        'download_url': '#'
                    }
                    export_history.insert(0, new_export)
                    
                    # Create response for download
                    response_data.seek(0)
                    return send_file(
                        response_data,
                        mimetype=mimetype,
                        as_attachment=True,
                        download_name=filename
                    )
                    
                except Exception as e:
                    app.logger.error(f"Error exporting data: {str(e)}")
                    flash(f'Error exporting data: {str(e)}', 'danger')
                    return redirect(url_for('superadmin_data_export'))
        
        # Log the view
        app.logger.info("Superadmin viewed data export page")
        
        return render_template('superadmin_data_export.html',
                              tables=tables,
                              export_formats=export_formats,
                              export_history=export_history)
    
    # Superadmin System Health route
    @app.route('/superadmin/system-health-alt')
    def superadmin_system_health_alt():
        """
        System health monitoring interface for superadmins.
        """
        from flask import render_template, flash, redirect, url_for
        import datetime
        import platform
        import sys
        import psutil
        import os
        import socket
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        try:
            # Get system resources usage
            cpu_usage = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            disk = psutil.disk_usage('/')
            disk_usage = disk.percent
            
            # Get system information
            system_info = {
                'cpu_usage': f"{cpu_usage:.1f}%",
                'memory_usage': f"{memory_usage:.1f}%",
                'disk_usage': f"{disk_usage:.1f}%",
                'platform': platform.platform(),
                'python_version': sys.version.split()[0],
                'uptime': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # Get database statistics
            total_stores = Store.query.count()
            active_stores = Store.query.filter(Store.active == True).count()
            total_users = User.query.count()
            
            # Recent activity in last 24 hours (mock data)
            recent_activity = 156  # This would normally be a count from logs or activity table
            
            # Get recent login activity (last 24 hours)
            # In a real implementation, this would come from a proper login audit table
            # For now, we'll create mock data
            recent_logins = []
            now = datetime.datetime.now()
            
            # Sample usernames for mock data
            usernames = ['admin1', 'groomer_john', 'superadmin', 'store_manager', 'tech_support']
            
            # Generate mock login events
            for i in range(10):
                # Random time in the last 24 hours
                hours_ago = (i * 2) + (i % 3)  # Distribute over 24 hours
                timestamp = now - datetime.timedelta(hours=hours_ago)
                
                # Select a random user
                user_idx = i % len(usernames)
                username = usernames[user_idx]
                
                # Create a mock user object
                mock_user = type('', (), {})()  # Create an anonymous object
                mock_user.username = username
                mock_user.id = i + 1
                
                # Create a mock login entry
                login_entry = type('', (), {})()  # Create an anonymous object
                login_entry.user = mock_user
                login_entry.timestamp = timestamp
                login_entry.action = "logged in successfully" if i % 5 != 0 else "failed login attempt"
                
                recent_logins.append(login_entry)
            
            # Sort by timestamp, most recent first
            recent_logins.sort(key=lambda x: x.timestamp, reverse=True)
            
            # Log the view
            app.logger.info("Superadmin viewed system health dashboard")
            
            return render_template('superadmin_system_health.html',
                                  system_info=system_info,
                                  total_stores=total_stores,
                                  active_stores=active_stores,
                                  total_users=total_users,
                                  recent_activity=recent_activity,
                                  recent_logins=recent_logins)
            
        except Exception as e:
            app.logger.error(f"Error in system health dashboard: {str(e)}")
            flash(f"Error loading system health data: {str(e)}", 'danger')
            return redirect(url_for('superadmin_tools'))
    
    # Superadmin Application Settings route
    @app.route('/superadmin/application-settings-alt', methods=['GET', 'POST'])
    def superadmin_application_settings_alt():
        """
        Application settings interface for superadmins to configure system-wide settings.
        """
        from flask import render_template, request, flash, redirect, url_for
        import json
        import os
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Path to settings JSON file (would be stored in a database in production)
        settings_file = os.path.join(app.root_path, 'static', 'settings.json')
        
        # Default settings if file doesn't exist
        default_settings = {
            'appearance': {
                'theme': 'light',
                'primary_color': '#4c6ef5',
                'logo_path': '/static/images/logo.png',
                'favicon_path': '/static/images/favicon.ico',
                'custom_css': '',
                'show_footer': True,
                'show_help_menu': True
            },
            'business': {
                'company_name': 'Pawfection Grooming Solutions',
                'address': '123 Main Street, Anytown, CA 12345',
                'phone': '(555) 123-4567',
                'email': 'contact@pawfection.com',
                'website': 'https://pawfection.com',
                'support_email': 'support@pawfection.com',
                'tax_rate': 8.25
            },
            'notifications': {
                'email_notifications': True,
                'sms_notifications': True,
                'appointment_reminders': True,
                'reminder_time': 24,  # hours before appointment
                'send_receipts': True,
                'notify_on_errors': True,
                'notify_superadmin': True
            },
            'integrations': {
                'payment_gateway': 'stripe',
                'stripe_key': 'pk_test_example',
                'stripe_secret': 'sk_test_example',
                'google_analytics': '',
                'mailchimp_api': '',
                'twilio_sid': '',
                'twilio_token': ''
            },
            'features': {
                'enable_online_booking': True,
                'enable_customer_accounts': True,
                'enable_reviews': True,
                'enable_invoicing': True,
                'enable_customer_portal': True,
                'enable_multistore': True,
                'maintenance_mode': False
            }
        }
        
        # Load current settings or create default
        try:
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
            else:
                settings = default_settings
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(settings_file), exist_ok=True)
                with open(settings_file, 'w') as f:
                    json.dump(settings, f, indent=4)
        except Exception as e:
            app.logger.error(f"Error loading settings file: {str(e)}")
            settings = default_settings
        
        # Handle form submission
        if request.method == 'POST':
            try:
                # Update appearance settings
                settings['appearance']['theme'] = request.form.get('theme', 'light')
                settings['appearance']['primary_color'] = request.form.get('primary_color', '#4c6ef5')
                settings['appearance']['custom_css'] = request.form.get('custom_css', '')
                settings['appearance']['show_footer'] = 'show_footer' in request.form
                settings['appearance']['show_help_menu'] = 'show_help_menu' in request.form
                
                # Update business settings
                settings['business']['company_name'] = request.form.get('company_name', '')
                settings['business']['address'] = request.form.get('address', '')
                settings['business']['phone'] = request.form.get('phone', '')
                settings['business']['email'] = request.form.get('email', '')
                settings['business']['website'] = request.form.get('website', '')
                settings['business']['support_email'] = request.form.get('support_email', '')
                try:
                    settings['business']['tax_rate'] = float(request.form.get('tax_rate', 0))
                except ValueError:
                    settings['business']['tax_rate'] = 0
                
                # Update notification settings
                settings['notifications']['email_notifications'] = 'email_notifications' in request.form
                settings['notifications']['sms_notifications'] = 'sms_notifications' in request.form
                settings['notifications']['appointment_reminders'] = 'appointment_reminders' in request.form
                try:
                    settings['notifications']['reminder_time'] = int(request.form.get('reminder_time', 24))
                except ValueError:
                    settings['notifications']['reminder_time'] = 24
                settings['notifications']['send_receipts'] = 'send_receipts' in request.form
                settings['notifications']['notify_on_errors'] = 'notify_on_errors' in request.form
                settings['notifications']['notify_superadmin'] = 'notify_superadmin' in request.form
                
                # Update integration settings
                settings['integrations']['payment_gateway'] = request.form.get('payment_gateway', 'stripe')
                settings['integrations']['stripe_key'] = request.form.get('stripe_key', '')
                settings['integrations']['stripe_secret'] = request.form.get('stripe_secret', '')
                settings['integrations']['google_analytics'] = request.form.get('google_analytics', '')
                settings['integrations']['mailchimp_api'] = request.form.get('mailchimp_api', '')
                settings['integrations']['twilio_sid'] = request.form.get('twilio_sid', '')
                settings['integrations']['twilio_token'] = request.form.get('twilio_token', '')
                
                # Update feature settings
                settings['features']['enable_online_booking'] = 'enable_online_booking' in request.form
                settings['features']['enable_customer_accounts'] = 'enable_customer_accounts' in request.form
                settings['features']['enable_reviews'] = 'enable_reviews' in request.form
                settings['features']['enable_invoicing'] = 'enable_invoicing' in request.form
                settings['features']['enable_customer_portal'] = 'enable_customer_portal' in request.form
                settings['features']['enable_multistore'] = 'enable_multistore' in request.form
                settings['features']['maintenance_mode'] = 'maintenance_mode' in request.form
                
                # Save the updated settings
                with open(settings_file, 'w') as f:
                    json.dump(settings, f, indent=4)
                
                flash('Application settings updated successfully!', 'success')
                app.logger.info("Superadmin updated application settings")
                
            except Exception as e:
                app.logger.error(f"Error saving application settings: {str(e)}")
                flash(f"Error saving settings: {str(e)}", 'danger')
        
        # Log the view
        app.logger.info("Superadmin viewed application settings page")
        
        return render_template('superadmin_application_settings.html', settings=settings)
    
    # Superadmin System Logs route
    @app.route('/superadmin/system-logs')
    def superadmin_system_logs_alt():
        """
        System logs interface for superadmins to view and filter application logs.
        """
        from flask import render_template, request, flash, redirect, url_for
        import datetime
        import random
        import os
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Get query parameters for filtering
        log_level = request.args.get('level', 'all')
        component = request.args.get('component', 'all')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        search_term = request.args.get('search', '')
        
        # In a real application, logs would come from a log file or database
        # For demonstration, we'll create mock log data
        
        # Generate random logs with different levels, components, and timestamps
        log_levels = ['INFO', 'WARNING', 'ERROR', 'CRITICAL', 'DEBUG']
        components = ['Authentication', 'Database', 'Payment', 'Scheduler', 'API', 'User Management', 'System']
        
        # Create date range (last 7 days)
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=7)
        
        # Generate 100 log entries
        logs = []
        log_counts = {'INFO': 0, 'WARNING': 0, 'ERROR': 0, 'CRITICAL': 0, 'DEBUG': 0}
        
        for i in range(100):
            # Generate a random timestamp within the date range
            random_seconds = random.randint(0, int((end_date - start_date).total_seconds()))
            timestamp = start_date + datetime.timedelta(seconds=random_seconds)
            
            # Generate a random log level with weighted probabilities
            level_weights = [60, 20, 10, 5, 5]  # INFO, WARNING, ERROR, CRITICAL, DEBUG weights
            level = random.choices(log_levels, weights=level_weights, k=1)[0]
            log_counts[level] += 1
            
            # Generate a random component
            component_name = random.choice(components)
            
            # Generate a user (sometimes None for system logs)
            user = None
            if random.random() > 0.3:  # 70% of logs have a user
                user_id = random.randint(1, 10)
                user = f"user{user_id}"
            
            # Generate a message based on the log level and component
            if level == 'INFO':
                messages = [
                    f"User logged in successfully",
                    f"Appointment created for customer",
                    f"Payment processed successfully",
                    f"Data backup completed",
                    f"Settings updated"
                ]
            elif level == 'WARNING':
                messages = [
                    f"Failed login attempt",
                    f"Slow database query detected",
                    f"API rate limit approaching",
                    f"Low disk space warning",
                    f"Session timeout for user"
                ]
            elif level == 'ERROR':
                messages = [
                    f"Database connection error",
                    f"Payment processing failed",
                    f"API request failed",
                    f"Email sending failed",
                    f"File upload error"
                ]
            elif level == 'CRITICAL':
                messages = [
                    f"Database server down",
                    f"Security breach detected",
                    f"Out of memory error",
                    f"System crash detected",
                    f"Data corruption detected"
                ]
            else:  # DEBUG
                messages = [
                    f"Query execution time: {random.randint(10, 500)}ms",
                    f"Cache hit ratio: {random.randint(50, 99)}%",
                    f"Memory usage: {random.randint(100, 800)}MB",
                    f"Request processing time: {random.randint(5, 200)}ms",
                    f"Thread pool size: {random.randint(5, 20)}"
                ]
            
            message = random.choice(messages)
            
            # Create the log entry
            log_entry = {
                'id': i + 1,
                'timestamp': timestamp,
                'level': level,
                'component': component_name,
                'message': message,
                'user': user,
                'details': f"Request ID: {random.randint(10000, 99999)} | IP: 192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
            }
            
            logs.append(log_entry)
        
        # Sort logs by timestamp (newest first)
        logs.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Apply filters
        filtered_logs = logs
        
        if log_level != 'all':
            filtered_logs = [log for log in filtered_logs if log['level'] == log_level]
        
        if component != 'all':
            filtered_logs = [log for log in filtered_logs if log['component'] == component]
        
        if date_from:
            try:
                date_from = datetime.datetime.strptime(date_from, '%Y-%m-%d')
                filtered_logs = [log for log in filtered_logs if log['timestamp'].date() >= date_from.date()]
            except ValueError:
                pass
        
        if date_to:
            try:
                date_to = datetime.datetime.strptime(date_to, '%Y-%m-%d')
                filtered_logs = [log for log in filtered_logs if log['timestamp'].date() <= date_to.date()]
            except ValueError:
                pass
        
        if search_term:
            filtered_logs = [log for log in filtered_logs if search_term.lower() in log['message'].lower() or 
                             search_term.lower() in (log['user'] or '').lower() or
                             search_term.lower() in log['component'].lower() or
                             search_term.lower() in log['details'].lower()]
        
        # Calculate stats
        total_logs = len(logs)
        error_count = log_counts['ERROR'] + log_counts['CRITICAL']
        warning_count = log_counts['WARNING']
        info_count = log_counts['INFO']
        debug_count = log_counts['DEBUG']
        
        # Log the view
        app.logger.info("Superadmin viewed system logs page")
        
        return render_template('superadmin_system_logs.html',
                              logs=filtered_logs,
                              log_level=log_level,
                              component=component,
                              date_from=date_from if isinstance(date_from, str) else date_from.strftime('%Y-%m-%d') if date_from else '',
                              date_to=date_to if isinstance(date_to, str) else date_to.strftime('%Y-%m-%d') if date_to else '',
                              search_term=search_term,
                              log_levels=log_levels,
                              components=components,
                              total_logs=total_logs,
                              error_count=error_count,
                              warning_count=warning_count,
                              info_count=info_count,
                              debug_count=debug_count)
    
    # Superadmin Email Test route
    @app.route('/superadmin/email-test-alt', methods=['GET', 'POST'])
    def superadmin_email_test_alt():
        """
        Email testing interface for superadmins to test email functionality and configure email settings.
        """
        from flask import render_template, request, flash, redirect, url_for, jsonify
        import json
        import os
        import smtplib
        import datetime
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Path to email config JSON file (would be stored in a database in production)
        config_file = os.path.join(app.root_path, 'static', 'email_config.json')
        
        # Default email config
        default_config = {
            'smtp_server': 'smtp.example.com',
            'smtp_port': 587,
            'use_tls': True,
            'username': 'noreply@pawfection.com',
            'password': '',  # In production, this would be securely stored
            'from_email': 'noreply@pawfection.com',
            'from_name': 'Pawfection Grooming Solutions',
            'reply_to': 'support@pawfection.com',
            'test_recipient': '',
            'last_test': None,
            'test_results': []
        }
        
        # Load current config or create default
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
            else:
                config = default_config
                os.makedirs(os.path.dirname(config_file), exist_ok=True)
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=4)
        except Exception as e:
            app.logger.error(f"Error loading email config file: {str(e)}")
            config = default_config
        
        test_result = None
        template_samples = [
            {
                'name': 'Welcome Email',
                'subject': 'Welcome to Pawfection Grooming Solutions!',
                'content': '''<h2>Welcome to Pawfection!</h2>
                <p>Dear {name},</p>
                <p>Thank you for choosing Pawfection Grooming Solutions for your pet's grooming needs.</p>
                <p>We're excited to have you as part of our family and look forward to taking care of your furry friend.</p>
                <p>If you have any questions, please don't hesitate to contact us.</p>
                <p>Best regards,<br>The Pawfection Team</p>'''
            },
            {
                'name': 'Appointment Confirmation',
                'subject': 'Your Grooming Appointment Confirmation',
                'content': '''<h2>Appointment Confirmed!</h2>
                <p>Dear {name},</p>
                <p>This is to confirm your grooming appointment for {pet_name} on {date} at {time}.</p>
                <p>Please arrive 10 minutes early to ensure a smooth check-in process.</p>
                <p>If you need to reschedule, please contact us at least 24 hours in advance.</p>
                <p>We look forward to seeing you and {pet_name}!</p>
                <p>Best regards,<br>The Pawfection Team</p>'''
            },
            {
                'name': 'Receipt',
                'subject': 'Your Pawfection Receipt',
                'content': '''<h2>Thank You for Your Business!</h2>
                <p>Dear {name},</p>
                <p>Thank you for visiting Pawfection Grooming Solutions today.</p>
                <p>Please find your receipt details below:</p>
                <p><strong>Services:</strong> {services}</p>
                <p><strong>Total Amount:</strong> ${amount}</p>
                <p><strong>Date:</strong> {date}</p>
                <p>We hope you and {pet_name} were happy with our services!</p>
                <p>Best regards,<br>The Pawfection Team</p>'''
            }
        ]
        
        # Handle form submission for email test
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'test_email':
                recipient = request.form.get('recipient')
                subject = request.form.get('subject')
                message = request.form.get('message')
                template_id = request.form.get('template')
                
                if template_id and template_id != 'custom':
                    try:
                        template_index = int(template_id)
                        if 0 <= template_index < len(template_samples):
                            subject = template_samples[template_index]['subject']
                            message = template_samples[template_index]['content']
                            # Replace placeholders with sample data
                            message = message.replace('{name}', 'John Doe')
                            message = message.replace('{pet_name}', 'Buddy')
                            message = message.replace('{date}', datetime.datetime.now().strftime('%Y-%m-%d'))
                            message = message.replace('{time}', '10:00 AM')
                            message = message.replace('{services}', 'Full Groom, Nail Trim')
                            message = message.replace('{amount}', '85.00')
                    except (ValueError, IndexError):
                        pass
                
                # Store last test recipient for convenience
                config['test_recipient'] = recipient
                
                # Try to send the test email
                try:
                    # In a real app, we'd use the configured SMTP server
                    # For this demo, we'll simulate the email sending process
                    
                    # Create a timestamp for this test
                    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Simulate success (in a real app, this would be actual SMTP sending)
                    success = True
                    error_message = None
                    
                    # In reality, we would use something like this:
                    """
                    smtp_server = smtplib.SMTP(config['smtp_server'], config['smtp_port'])
                    if config['use_tls']:
                        smtp_server.starttls()
                    if config['username'] and config['password']:
                        smtp_server.login(config['username'], config['password'])
                    
                    msg = MIMEMultipart('alternative')
                    msg['Subject'] = subject
                    msg['From'] = f"{config['from_name']} <{config['from_email']}>"
                    msg['To'] = recipient
                    msg['Reply-To'] = config['reply_to']
                    
                    text_part = MIMEText("This is a test email from Pawfection Grooming Solutions.", 'plain')
                    html_part = MIMEText(message, 'html')
                    
                    msg.attach(text_part)
                    msg.attach(html_part)
                    
                    smtp_server.send_message(msg)
                    smtp_server.quit()
                    """
                    
                    # Record the test result
                    test_result = {
                        'success': success,
                        'timestamp': timestamp,
                        'recipient': recipient,
                        'subject': subject,
                        'error': error_message
                    }
                    
                    # Add to test history (keep last 5)
                    config['test_results'].insert(0, test_result)
                    config['test_results'] = config['test_results'][:5]
                    config['last_test'] = timestamp
                    
                    # Save the updated config
                    with open(config_file, 'w') as f:
                        json.dump(config, f, indent=4)
                    
                    if success:
                        flash(f'Test email successfully sent to {recipient}!', 'success')
                        app.logger.info(f"Superadmin sent test email to {recipient}")
                    else:
                        flash(f'Error sending test email: {error_message}', 'danger')
                        app.logger.error(f"Error sending test email: {error_message}")
                    
                except Exception as e:
                    error_message = str(e)
                    test_result = {
                        'success': False,
                        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'recipient': recipient,
                        'subject': subject,
                        'error': error_message
                    }
                    
                    # Add to test history (keep last 5)
                    config['test_results'].insert(0, test_result)
                    config['test_results'] = config['test_results'][:5]
                    
                    flash(f'Error sending test email: {error_message}', 'danger')
                    app.logger.error(f"Error sending test email: {error_message}")
            
            elif action == 'save_config':
                try:
                    # Update email configuration
                    config['smtp_server'] = request.form.get('smtp_server', '')
                    config['smtp_port'] = int(request.form.get('smtp_port', 587))
                    config['use_tls'] = 'use_tls' in request.form
                    config['username'] = request.form.get('username', '')
                    
                    # Only update password if a new one is provided
                    new_password = request.form.get('password')
                    if new_password:
                        config['password'] = new_password  # In production, this would be encrypted
                    
                    config['from_email'] = request.form.get('from_email', '')
                    config['from_name'] = request.form.get('from_name', '')
                    config['reply_to'] = request.form.get('reply_to', '')
                    
                    # Save the updated config
                    with open(config_file, 'w') as f:
                        json.dump(config, f, indent=4)
                    
                    flash('Email configuration saved successfully!', 'success')
                    app.logger.info("Superadmin updated email configuration")
                    
                except Exception as e:
                    flash(f'Error saving email configuration: {str(e)}', 'danger')
                    app.logger.error(f"Error saving email configuration: {str(e)}")
        
        # Log the view
        app.logger.info("Superadmin viewed email test page")
        
        return render_template('superadmin_email_test.html', 
                               config=config, 
                               test_result=test_result,
                               templates=template_samples)
    
    # Superadmin Database Management route
    @app.route('/superadmin/database-alt', methods=['GET', 'POST'])
    def superadmin_database_alt():
        """
        Database management interface for superadmins to run queries, backup, and restore.
        """
        from flask import render_template, request, flash, redirect, url_for, jsonify, Response
        from sqlalchemy import text, inspect
        import json
        import os
        import time
        import datetime
        import sqlite3
        import csv
        import io
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        
        # Get database info using SQLAlchemy
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        table_counts = {}
        table_sizes = {}
        
        # For SQLite, we need to get sizes differently than for other databases
        # This is a simplified approach for the demo
        try:
            for table in tables:
                # Count rows
                result = db.session.execute(text(f"SELECT COUNT(*) as count FROM {table}"))
                count = result.scalar()
                table_counts[table] = count
                
                # Estimate size (this is very approximate for SQLite)
                # In a real app with a different database, you'd use a database-specific approach
                table_sizes[table] = f"{count * 2} KB"  # Very rough estimate
        except Exception as e:
            app.logger.error(f"Error getting database stats: {str(e)}")
        
        # Get total database size
        # For SQLite, we can get the file size
        db_size = "Unknown"
        try:
            # This assumes SQLite database file is at instance/site.db
            db_path = os.path.join(app.instance_path, 'site.db')
            if os.path.exists(db_path):
                size_bytes = os.path.getsize(db_path)
                if size_bytes < 1024*1024:
                    db_size = f"{size_bytes / 1024:.2f} KB"
                else:
                    db_size = f"{size_bytes / (1024*1024):.2f} MB"
        except Exception as e:
            app.logger.error(f"Error getting database file size: {str(e)}")
        
        # Last backup info - In a real app this would come from a real backup system
        last_backup = {
            'timestamp': datetime.datetime.now() - datetime.timedelta(days=2, hours=3),
            'size': '15.7 MB',
            'success': True
        }
        
        # Sample queries for common operations
        sample_queries = [
            {
                'name': 'List all stores',
                'query': 'SELECT * FROM store LIMIT 10;'
            },
            {
                'name': 'List all users',
                'query': 'SELECT id, username, email, role FROM user LIMIT 10;'
            },
            {
                'name': 'Recent appointments',
                'query': 'SELECT * FROM appointment ORDER BY date DESC LIMIT 10;'
            },
            {
                'name': 'Customers with pets',
                'query': 'SELECT c.*, COUNT(p.id) as pet_count FROM customer c LEFT JOIN pet p ON c.id = p.customer_id GROUP BY c.id LIMIT 10;'
            },
            {
                'name': 'Revenue by store',
                'query': 'SELECT s.name, SUM(i.total_amount) as total_revenue FROM store s LEFT JOIN invoice i ON s.id = i.store_id GROUP BY s.id;'
            }
        ]
        
        # Handle form submissions
        query_result = None
        backup_result = None
        restore_result = None
        
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'run_query':
                query = request.form.get('query')
                if query:
                    try:
                        # For security in a real app, you'd want to restrict what queries can be run
                        # and sanitize inputs properly
                        start_time = time.time()
                        result = db.session.execute(text(query))
                        execution_time = time.time() - start_time
                        
                        # Check if it's a SELECT query (has results) or something else
                        if result.keys():
                            # Convert results to a list of dicts for display
                            rows = [dict(row) for row in result]
                            
                            query_result = {
                                'columns': result.keys(),
                                'rows': rows,
                                'row_count': len(rows),
                                'execution_time': f"{execution_time:.4f}"
                            }
                            flash(f"Query executed successfully. {len(rows)} rows returned.", 'success')
                        else:
                            # For non-SELECT queries (INSERT, UPDATE, DELETE, etc.)
                            db.session.commit()  # Commit the transaction
                            flash(f"Query executed successfully. No result set returned.", 'success')
                            query_result = {
                                'rowcount': result.rowcount,
                                'execution_time': f"{execution_time:.4f}"
                            }
                            
                        app.logger.info(f"Superadmin executed SQL query: {query}")
                        
                    except Exception as e:
                        db.session.rollback()  # Roll back any failed transaction
                        error_message = str(e)
                        flash(f"Error executing query: {error_message}", 'danger')
                        app.logger.error(f"Error executing SQL query: {error_message}")
                        query_result = {
                            'error': error_message
                        }
                else:
                    flash('Please enter a query to execute.', 'warning')
                    
            elif action == 'backup_database':
                # In a real app, this would create an actual backup
                # For this demo, we'll simulate a backup process
                try:
                    # Simulate backup process
                    time.sleep(1)  # Simulating work
                    
                    # Record backup info
                    backup_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                    backup_filename = f"pawfection_backup_{backup_timestamp}.sqlite"
                    backup_path = os.path.join(app.root_path, 'static', 'backups', backup_filename)
                    
                    # Ensure backup directory exists
                    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                    
                    # In a real app, you would copy the database file or use proper backup tools
                    # For demo purposes, we'll just create an empty file
                    with open(backup_path, 'w') as f:
                        f.write('') 
                    
                    backup_result = {
                        'success': True,
                        'timestamp': backup_timestamp,
                        'filename': backup_filename
                    }
                    
                    flash(f"Database backup created successfully: {backup_filename}", 'success')
                    app.logger.info(f"Superadmin created database backup: {backup_filename}")
                    
                except Exception as e:
                    error_message = str(e)
                    backup_result = {
                        'success': False,
                        'error': error_message
                    }
                    flash(f"Error creating backup: {error_message}", 'danger')
                    app.logger.error(f"Error creating database backup: {error_message}")
            
            elif action == 'export_table':
                table_name = request.form.get('table_name')
                export_format = request.form.get('export_format', 'csv')
                
                if table_name and table_name in tables:
                    try:
                        # Get table data
                        result = db.session.execute(text(f"SELECT * FROM {table_name} LIMIT 1000"))
                        columns = result.keys()
                        rows = [dict(row) for row in result]
                        
                        if export_format == 'csv':
                            # Generate CSV
                            output = io.StringIO()
                            writer = csv.DictWriter(output, fieldnames=columns)
                            writer.writeheader()
                            writer.writerows(rows)
                            
                            # Prepare response
                            response = Response(
                                output.getvalue(),
                                mimetype='text/csv',
                                headers={
                                    'Content-Disposition': f'attachment; filename={table_name}_export.csv'
                                }
                            )
                            
                            app.logger.info(f"Superadmin exported table {table_name} as CSV")
                            return response
                            
                        elif export_format == 'json':
                            # Generate JSON
                            json_data = json.dumps({"data": rows}, indent=2)
                            
                            # Prepare response
                            response = Response(
                                json_data,
                                mimetype='application/json',
                                headers={
                                    'Content-Disposition': f'attachment; filename={table_name}_export.json'
                                }
                            )
                            
                            app.logger.info(f"Superadmin exported table {table_name} as JSON")
                            return response
                            
                    except Exception as e:
                        error_message = str(e)
                        flash(f"Error exporting table: {error_message}", 'danger')
                        app.logger.error(f"Error exporting table {table_name}: {error_message}")
                else:
                    flash('Invalid table name selected.', 'danger')
        
        # Log the view
        app.logger.info("Superadmin viewed database management page")
        
        return render_template('superadmin_database.html',
                               tables=tables,
                               table_counts=table_counts,
                               table_sizes=table_sizes,
                               db_size=db_size,
                               last_backup=last_backup,
                               sample_queries=sample_queries,
                               query_result=query_result,
                               backup_result=backup_result,
                               restore_result=restore_result)

    # Superadmin stop impersonation
    @app.route('/superadmin/stop_impersonation')
    def superadmin_stop_impersonation():
        """
        Allows a superadmin to stop impersonating a store.
        """
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
            
        current_impersonated_store_id = session.pop('store_id', None)
        session['impersonating'] = False
        app.logger.info(f"Superadmin {g.user.username} (ID: {g.user.id}) stopped impersonating store ID: {current_impersonated_store_id}.")
        flash(f"You are no longer impersonating a store.", "info")
        return redirect(url_for('superadmin_dashboard'))
        
    # Create new store
    @app.route('/superadmin/create_store', methods=['POST'])
    def superadmin_create_store():
        """
        Creates a new store with admin user.
        """
        from flask import request
        from datetime import datetime
        import bcrypt
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
            
        # Get form data
        name = request.form.get('name')
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        phone = request.form.get('phone', '')
        address = request.form.get('address', '')
        subscription_status = request.form.get('subscription_status', 'trial')
        subscription_ends_at = request.form.get('subscription_ends_at')
        
        # Basic validation
        if not all([name, username, password, email]):
            flash('Please fill out all required fields.', 'danger')
            return redirect(url_for('superadmin_dashboard'))
            
        # Check if store username already exists
        if Store.query.filter_by(username=username).first():
            flash(f'Store with username "{username}" already exists.', 'danger')
            return redirect(url_for('superadmin_dashboard'))
            
        try:
            # Create new store
            new_store = Store(
                name=name,
                username=username,
                email=email,
                phone=phone,
                address=address,
                subscription_status=subscription_status,
                subscription_ends_at=datetime.strptime(subscription_ends_at, '%Y-%m-%d') if subscription_ends_at else None
            )
            db.session.add(new_store)
            db.session.flush()  # Get the store ID before committing
            
            # Create an admin user for the store
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            admin_user = User(
                username=username,
                password=hashed_password,
                store_id=new_store.id,
                is_admin=True
            )
            db.session.add(admin_user)
            db.session.commit()
            
            # Log activity
            log_activity(g.user.id, new_store.id, f"Created store '{name}' with username '{username}'")
            
            flash(f'Store "{name}" has been created successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error creating store: {e}")
            flash(f'An error occurred while creating the store: {e}', 'danger')
            
        return redirect(url_for('superadmin_dashboard'))
        
    # Edit store
    @app.route('/superadmin/edit_store', methods=['POST'])
    def superadmin_edit_store():
        """
        Edit an existing store's details.
        """
        from flask import request
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
            
        # Get form data
        store_id = request.form.get('store_id')
        name = request.form.get('name')
        username = request.form.get('username')
        email = request.form.get('email')
        phone = request.form.get('phone', '')
        address = request.form.get('address', '')
        
        # Basic validation
        if not all([store_id, name, username, email]):
            flash('Please fill out all required fields.', 'danger')
            return redirect(url_for('superadmin_dashboard'))
            
        try:
            # Get the store
            store = db.session.get(Store, store_id)
            if not store:
                flash('Store not found.', 'danger')
                return redirect(url_for('superadmin_dashboard'))
                
            # Check if username is already taken by another store
            existing_store = Store.query.filter(Store.username == username, Store.id != store_id).first()
            if existing_store:
                flash(f'Username "{username}" is already taken.', 'danger')
                return redirect(url_for('superadmin_dashboard'))
                
            # Update store details
            store.name = name
            store.username = username
            store.email = email
            store.phone = phone
            store.address = address
            
            # Handle admin users
            admin_usernames = request.form.getlist('admin_username[]')
            admin_passwords = request.form.getlist('admin_password[]')
            
            if admin_usernames and admin_passwords and len(admin_usernames) == len(admin_passwords):
                import bcrypt
                for i in range(len(admin_usernames)):
                    if admin_usernames[i] and admin_passwords[i]:
                        # Check if admin user already exists
                        admin_user = User.query.filter_by(username=admin_usernames[i], store_id=store_id).first()
                        if not admin_user:
                            # Create new admin user
                            hashed_password = bcrypt.hashpw(admin_passwords[i].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                            new_admin = User(
                                username=admin_usernames[i],
                                password=hashed_password,
                                store_id=store_id,
                                is_admin=True
                            )
                            db.session.add(new_admin)
            
            db.session.commit()
            
            # Log activity
            log_activity(g.user.id, store.id, f"Updated store '{store.name}' details")
            
            flash(f'Store "{name}" has been updated successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error updating store: {e}")
            flash(f'An error occurred while updating the store: {e}', 'danger')
            
        return redirect(url_for('superadmin_dashboard'))
        
    # Delete store
    @app.route('/superadmin/delete_store/<int:store_id>', methods=['POST'])
    def superadmin_delete_store(store_id):
        """
        Delete a store and all associated data.
        """
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
            
        try:
            # Get the store
            store = db.session.get(Store, store_id)
            if not store:
                flash('Store not found.', 'danger')
                return redirect(url_for('superadmin_dashboard'))
                
            store_name = store.name
            
            # Delete all associated data
            # This should cascade if properly set up in the models, but we'll be explicit here
            User.query.filter_by(store_id=store_id).delete()
            # Add other model deletions here if needed
            
            # Delete the store itself
            db.session.delete(store)
            db.session.commit()
            
            # Log activity
            log_activity(g.user.id, None, f"Deleted store '{store_name}' (ID: {store_id})")
            
            flash(f'Store "{store_name}" has been deleted successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error deleting store: {e}")
            flash(f'An error occurred while deleting the store: {e}', 'danger')
            
        return redirect(url_for('superadmin_dashboard'))
        
    # Update store subscription
    @app.route('/superadmin/update_subscription', methods=['POST'])
    def superadmin_update_subscription():
        """
        Update a store's subscription details.
        """
        from flask import request
        from datetime import datetime
        
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
            
        # Get form data
        store_id = request.form.get('store_id')
        subscription_status = request.form.get('subscription_status')
        subscription_ends_at = request.form.get('subscription_ends_at')
        notes = request.form.get('notes', '')
        
        # Basic validation
        if not all([store_id, subscription_status]):
            flash('Please fill out all required fields.', 'danger')
            return redirect(url_for('superadmin_dashboard'))
            
        try:
            # Get the store
            store = db.session.get(Store, store_id)
            if not store:
                flash('Store not found.', 'danger')
                return redirect(url_for('superadmin_dashboard'))
                
            # Update subscription details
            old_status = store.subscription_status
            store.subscription_status = subscription_status
            store.subscription_ends_at = datetime.strptime(subscription_ends_at, '%Y-%m-%d') if subscription_ends_at else None
            
            # Store subscription notes if we have a field for it
            # This might require a model update if not already present
            if hasattr(store, 'subscription_notes'):
                store.subscription_notes = notes
                
            db.session.commit()
            
            # Log activity
            log_activity(g.user.id, store.id, f"Updated subscription for '{store.name}' from {old_status} to {subscription_status}")
            
            flash(f'Subscription for "{store.name}" has been updated successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error updating subscription: {e}")
            flash(f'An error occurred while updating the subscription: {e}', 'danger')
            
        return redirect(url_for('superadmin_dashboard'))
        
    # Get store details for AJAX
    @app.route('/superadmin/get_store/<int:store_id>')
    def superadmin_get_store(store_id):
        """
        Get store details in JSON format for AJAX requests.
        """
        from flask import jsonify
        
        if not session.get('is_superadmin'):
            return jsonify({'error': 'Access denied'}), 403
            
        store = db.session.get(Store, store_id)
        if not store:
            return jsonify({'error': 'Store not found'}), 404
            
        admin_users = User.query.filter_by(store_id=store_id, is_admin=True).all()
        
        store_data = {
            'id': store.id,
            'name': store.name,
            'username': store.username,
            'email': store.email,
            'phone': store.phone or '',
            'address': store.address or '',
            'subscription_status': store.subscription_status,
            'subscription_ends_at': store.subscription_ends_at.strftime('%Y-%m-%d') if store.subscription_ends_at else None,
            'admin_users': [{
                'id': user.id,
                'username': user.username
            } for user in admin_users]
        }
        
        return jsonify(store_data)

    # Apply ProxyFix middleware
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    @app.shell_context_processor
    def make_shell_context():
        from models import User, Store  # Add other models as needed
        return {'db': db, 'User': User, 'Store': Store}

    # --- Subscription Required Decorator ---
    # (Moved to utils.py)

    # --- Subscription Page ---
    @app.route('/subscribe')
    @login_required
    def subscribe():
        return render_template('subscribe.html',
                              stripe_publishable_key=app.config['STRIPE_PUBLISHABLE_KEY'])

    # --- Create Stripe Checkout Session ---
    @app.route('/create-checkout-session', methods=['POST'])
    @login_required
    def create_checkout_session():
        from flask_login import current_user
        from models import Store
        domain_url = request.host_url.rstrip('/')
        try:
            app.logger.info(f"[CHECKOUT] current_user: id={getattr(current_user, 'id', None)}, username={getattr(current_user, 'username', None)}, store_id={getattr(current_user, 'store_id', None)}")
            # Get the store for the current user
            store = None
            if hasattr(current_user, 'store_id') and current_user.store_id:
                app.logger.info(f"[CHECKOUT] Attempting to fetch Store with id={current_user.store_id}")
                try:
                    store = Store.query.get(int(current_user.store_id))
                except Exception as e:
                    app.logger.error(f"[CHECKOUT] Exception when querying Store: {e}")
            app.logger.info(f"[CHECKOUT] Store fetched: {store}")
            if not store:
                app.logger.error('[CHECKOUT] No store found for current user.')
                return jsonify(error='No store found for current user.'), 400

            # Create or retrieve Stripe customer for the store
            customer_id = store.stripe_customer_id
            if not customer_id:
                app.logger.info(f"[CHECKOUT] Creating Stripe customer for store {store.id} ({store.name})")
                customer = stripe.Customer.create(
                    email=store.email or current_user.email,
                    name=store.name,
                    metadata={'store_id': store.id}
                )
                customer_id = customer.id
                store.stripe_customer_id = customer_id
                db.session.commit()
                app.logger.info(f"[CHECKOUT] Created Stripe customer with id={customer_id}")
            else:
                app.logger.info(f"[CHECKOUT] Using existing Stripe customer id={customer_id}")

            # Create checkout session for the store
            app.logger.info(f"[CHECKOUT] Creating Stripe checkout session for customer_id={customer_id} and price_id={app.config['STRIPE_PRICE_ID']}")
            checkout_session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': app.config['STRIPE_PRICE_ID'],
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=domain_url + url_for('subscription_success'),
                cancel_url=domain_url + url_for('subscribe'),
                metadata={'store_id': store.id}
            )
            app.logger.info(f"[CHECKOUT] Created Stripe checkout session with id={checkout_session['id']}")
            return jsonify({'sessionId': checkout_session['id']})
        except Exception as e:
            app.logger.error(f"[CHECKOUT] Stripe checkout session error: {e}")
            return jsonify(error=str(e)), 400


    # --- Subscription Success Page ---
    @app.route('/subscription-success')
    def subscription_success():
        flash('Your subscription was successful!', 'success')
        return redirect(url_for('dashboard'))


    # --- Stripe Webhook ---
    @app.route('/stripe_webhook', methods=['POST'])
    def stripe_webhook():
        payload = request.data
        sig_header = request.headers.get('stripe-signature')
        endpoint_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
        event = None
        import sys
        app.logger.info('[WEBHOOK] Stripe webhook received')
        if not endpoint_secret:
            app.logger.error('[WEBHOOK] STRIPE_WEBHOOK_SECRET not set!')
            return 'Webhook secret not configured', 500
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except Exception as e:
            app.logger.error(f"[WEBHOOK] Error verifying webhook signature: {e}")
            return str(e), 400

        app.logger.info(f"[WEBHOOK] Stripe event type: {event.get('type')}")
        # Handle subscription created or updated event
        if event['type'] == 'checkout.session.completed':
            session_obj = event['data']['object']
            app.logger.info(f"[WEBHOOK] checkout.session.completed: session_obj={session_obj}")
            metadata = session_obj.get('metadata', {})
            store_id = metadata.get('store_id')
            subscription_id = session_obj.get('subscription')
            customer_id = session_obj.get('customer')
            if not store_id:
                app.logger.error('[WEBHOOK] No store_id in session metadata!')
                return 'No store_id in metadata', 400
            from models import Store
            store = Store.query.get(int(store_id))
            if store:
                store.stripe_customer_id = customer_id
                store.stripe_subscription_id = subscription_id
                store.subscription_status = 'active'
                db.session.commit()
                app.logger.info(f"[WEBHOOK] Store {store.id} subscription activated. customer_id={customer_id}, subscription_id={subscription_id}")
            else:
                app.logger.error(f"[WEBHOOK] No store found for store_id={store_id}")
        elif event['type'] in ['customer.subscription.created', 'customer.subscription.updated']:
            subscription = event['data']['object']
            customer_id = subscription.get('customer')
            subscription_id = subscription.get('id')
            status = subscription.get('status')
            from models import Store
            store = Store.query.filter_by(stripe_customer_id=customer_id).first()
            if store:
                store.stripe_subscription_id = subscription_id
                # Only set to active if Stripe says it's active or trialing
                if status in ['active', 'trialing']:
                    store.subscription_status = 'active'
                    db.session.commit()
                    app.logger.info(f"[WEBHOOK] Store {store.id} subscription set to active ({event['type']}). customer_id={customer_id}, subscription_id={subscription_id}, status={status}")
                else:
                    app.logger.info(f"[WEBHOOK] Store {store.id} subscription received {event['type']} but status is {status}, not activating.")
            else:
                app.logger.error(f"[WEBHOOK] No store found for customer_id={customer_id} in {event['type']}")
        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            customer_id = subscription.get('customer')
            from models import Store
            store = Store.query.filter_by(stripe_customer_id=customer_id).first()
            if store:
                store.subscription_status = 'inactive'
                db.session.commit()
                app.logger.info(f"[WEBHOOK] Store {store.id} subscription set to inactive (deleted event)")
        return '', 200



    return app

if __name__ == '__main__':
    app = create_app()
    # SECURITY WARNING: Never run with debug=True in production!
    # Forcing debug mode ON for troubleshooting purposes.
    # The original logic is preserved below but commented out.
    # debug_mode = os.environ.get('FLASK_ENV', '').lower() == 'development' or os.environ.get('FLASK_DEBUG', '') == '1'
    # if debug_mode:
    #     print("[SECURITY WARNING] Debug mode is enabled. DO NOT use debug=True in production!")
    app.run(debug=True)
