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
    debug_mode = os.environ.get('FLASK_ENV', '').lower() == 'development' or os.environ.get('FLASK_DEBUG', '') == '1'
    if debug_mode:
        print("[SECURITY WARNING] Debug mode is enabled. DO NOT use debug=True in production!")
    app.run(debug=debug_mode)
