# app.py
import os
import bcrypt
from flask import Flask, g, session, redirect, url_for, flash, send_from_directory
from flask.wrappers import Request
from extensions import db
from models import *
from auth import auth_bp
from owners import owners_bp
from dogs import dogs_bp
from appointments import appointments_bp
from management import management_bp
from functools import wraps

def create_app():
    app = Flask(__name__)
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    PERSISTENT_DATA_ROOT = os.environ.get('PERSISTENT_DATA_DIR', BASE_DIR)
    DATABASE_PATH = os.path.join(PERSISTENT_DATA_ROOT, 'grooming_business_v2.db')
    UPLOAD_FOLDER = os.path.join(PERSISTENT_DATA_ROOT, 'uploads')
    SHARED_TOKEN_FILE = os.path.join(PERSISTENT_DATA_ROOT, 'shared_google_token.json')
    NOTIFICATION_SETTINGS_FILE = os.path.join(PERSISTENT_DATA_ROOT, 'notification_settings.json')

    app.config['SECRET_KEY'] = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))
    # Use DATABASE_URL for PostgreSQL if set, otherwise fallback to SQLite
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

    db.init_app(app)

    # Route to serve uploaded files
    @app.route('/uploads/<path:filename>')
    def uploaded_persistent_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # Ensure all tables are created on startup
    with app.app_context():
        db.create_all()

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(dogs_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(management_bp)

    # Set g.user before each request
    @app.before_request
    def load_logged_in_user():
        user_id = session.get('user_id')
        if user_id is None:
            g.user = None
        else:
            g.user = User.query.get(user_id)

    # Decorator to require login
    def login_required(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('auth.login'))
            return view(**kwargs)
        return wrapped_view

    # Add root route for home page
    @app.route('/')
    def home():
        from flask import render_template
        return render_template('home_page.html')

    # Add legal pages routes
    @app.route('/user-agreement')
    def view_user_agreement():
        from flask import render_template
        return render_template('user_agreement.html')

    @app.route('/privacy-policy')
    def view_privacy_policy():
        from flask import render_template
        return render_template('privacy_policy.html')

    # Add dashboard route
    @app.route('/dashboard')
    @login_required
    def dashboard():
        from flask import render_template
        return render_template('dashboard.html')

    # Add store login route
    @app.route('/store/login', methods=['GET', 'POST'])
    def store_login():
        from flask import render_template, request
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            store = Store.query.filter_by(username=username).first()
            if store and store.check_password(password):
                session['store_id'] = store.id
                flash(f"Store '{store.name}' logged in. Please sign in as a user.", "success")
                return redirect(url_for('auth.login'))
            else:
                flash('Invalid store username or password.', 'danger')
        return render_template('store_login.html')

    # Add superadmin login route
    @app.route('/superadmin/login', methods=['GET', 'POST'])
    def superadmin_login():
        from flask import render_template, request
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            user = User.query.filter_by(username=username, role='superadmin').first()
            if user and user.check_password(password):
                session.clear()
                session['user_id'] = user.id
                session['is_superadmin'] = True
                session.permanent = True
                flash(f"Superadmin '{user.username}' logged in.", "success")
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid superadmin username or password.', 'danger')
        return render_template('superadmin_login.html')

    # Add store registration route
    @app.route('/store/register', methods=['GET', 'POST'])
    def store_register():
        from flask import render_template, request
        if request.method == 'POST':
            store_name = request.form.get('store_name')
            store_username = request.form.get('store_username')
            store_password = request.form.get('store_password')
            admin_username = request.form.get('admin_username')
            admin_password = request.form.get('admin_password')
            errors = []
            if not store_name or not store_username or not store_password or not admin_username or not admin_password:
                errors.append('All fields are required.')
            if len(store_password) < 8 or len(admin_password) < 8:
                errors.append('Passwords must be at least 8 characters.')
            if Store.query.filter_by(username=store_username).first():
                errors.append('Store username already exists.')
            if User.query.filter_by(username=admin_username).first():
                errors.append('Admin username already exists.')
            if errors:
                for error in errors:
                    flash(error, 'danger')
                return render_template('store_register.html'), 400
            # Create store
            store = Store(name=store_name, username=store_username)
            store.set_password(store_password)
            db.session.add(store)
            db.session.commit()
            # Create admin user for this store
            admin_user = User(username=admin_username, role='admin', is_admin=True, is_groomer=True, store_id=store.id)
            admin_user.set_password(admin_password)
            db.session.add(admin_user)
            db.session.commit()
            flash('Store and admin account created! Please log in to your store.', 'success')
            return redirect(url_for('store_login'))
        return render_template('store_register.html')

    # Add superadmin dashboard route
    @app.route('/superadmin/dashboard')
    def superadmin_dashboard():
        from flask import render_template
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        stores = Store.query.all()
        # Get admin users for each store
        store_admins = {store.id: User.query.filter_by(store_id=store.id, role='admin').all() for store in stores}
        return render_template('superadmin_dashboard.html', stores=stores, store_admins=store_admins)

    # Add superadmin tools route
    @app.route('/superadmin/tools')
    def superadmin_tools():
        from flask import render_template
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        return render_template('superadmin_tools.html')

    # Superadmin impersonate store
    @app.route('/superadmin/impersonate/<int:store_id>')
    def superadmin_impersonate(store_id):
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        session['store_id'] = store_id
        session['impersonating'] = True
        flash('Now impersonating store.', 'info')
        return redirect(url_for('dashboard'))

    # Superadmin stop impersonation
    @app.route('/superadmin/stop_impersonation')
    def superadmin_stop_impersonation():
        if not session.get('is_superadmin'):
            flash('Access denied.', 'danger')
            return redirect(url_for('superadmin_login'))
        session.pop('store_id', None)
        session.pop('impersonating', None)
        flash('Stopped impersonating store.', 'info')
        return redirect(url_for('superadmin_dashboard'))

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
