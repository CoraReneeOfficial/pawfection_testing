# app.py
import os
import bcrypt
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, func, cast, Date 
import datetime 
from datetime import timezone, timedelta 
from werkzeug.utils import secure_filename
import uuid
from decimal import Decimal, InvalidOperation 
import webbrowser
import threading
import time
import json
import socket
import calendar 

# --- Google OAuth & API Imports ---
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import google.auth.transport.requests 
from dateutil import tz, parser as dateutil_parser 

# --- Configuration ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# MODIFIED FOR RAILWAY: Use PERSISTENT_DATA_ROOT for paths that need to be on a volume
PERSISTENT_DATA_ROOT = os.environ.get('PERSISTENT_DATA_DIR', BASE_DIR) 

DATABASE_PATH = os.path.join(PERSISTENT_DATA_ROOT, 'grooming_business_v2.db')
UPLOAD_FOLDER = os.path.join(PERSISTENT_DATA_ROOT, 'uploads') # Files uploaded by users
SHARED_TOKEN_FILE = os.path.join(PERSISTENT_DATA_ROOT, 'shared_google_token.json')
SHARED_GOOGLE_CALENDAR_ID = 'primary'

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "142623477405-usk2u3huejpoj62djb3gr267aov37cad.apps.googleusercontent.com")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "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")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", 'http://127.0.0.1:5000/google/callback')


GOOGLE_SCOPES = ['https://www.googleapis.com/auth/calendar.readonly', 'https://www.googleapis.com/auth/calendar.events']
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 

BUSINESS_TIMEZONE_NAME = os.environ.get("BUSINESS_TIMEZONE", 'America/New_York')
BUSINESS_TIMEZONE = tz.gettz(BUSINESS_TIMEZONE_NAME)
if BUSINESS_TIMEZONE is None:
    BUSINESS_TIMEZONE = tz.tzlocal() 
    # app.logger not available yet at top level
    print(f"WARNING: Could not load timezone '{BUSINESS_TIMEZONE_NAME}'. Falling back to system local: {BUSINESS_TIMEZONE.zone}")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER 
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 
app.config['SHARED_TOKEN_FILE'] = SHARED_TOKEN_FILE 

db = SQLAlchemy(app)

# --- Database Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_groomer = db.Column(db.Boolean, default=False, nullable=False) 
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    picture_filename = db.Column(db.String(200), nullable=True)

    activity_logs = db.relationship('ActivityLog', backref='user', lazy=True)
    created_owners = db.relationship('Owner', backref='creator', lazy='dynamic', foreign_keys='Owner.created_by_user_id')
    created_dogs = db.relationship('Dog', backref='creator', lazy='dynamic', foreign_keys='Dog.created_by_user_id')
    created_services = db.relationship('Service', backref='creator', lazy='dynamic', foreign_keys='Service.created_by_user_id')
    created_appointments = db.relationship('Appointment', backref='creator', lazy='dynamic', foreign_keys='Appointment.created_by_user_id')
    assigned_appointments = db.relationship('Appointment', backref='groomer', lazy='dynamic', foreign_keys='Appointment.groomer_id')

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def __repr__(self):
        return f"<User {self.username} (ID: {self.id}, Admin: {self.is_admin}, Groomer: {self.is_groomer})>"

class Owner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    address = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    dogs = db.relationship('Dog', backref='owner', lazy='joined', cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Owner {self.name} (ID: {self.id})>"

class Dog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    breed = db.Column(db.String(100), nullable=True)
    birthday = db.Column(db.String(10), nullable=True)
    temperament = db.Column(db.Text, nullable=True)
    hair_style_notes = db.Column(db.Text, nullable=True)
    aggression_issues = db.Column(db.Text, nullable=True)
    anxiety_issues = db.Column(db.Text, nullable=True)
    other_notes = db.Column(db.Text, nullable=True)
    picture_filename = db.Column(db.String(200), nullable=True) 
    owner_id = db.Column(db.Integer, db.ForeignKey('owner.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    appointments = db.relationship('Appointment', backref='dog', lazy='dynamic', cascade="all, delete-orphan", order_by="desc(Appointment.appointment_datetime)")

    def __repr__(self):
        return f"<Dog {self.name} (ID: {self.id}), Owner ID: {self.owner_id}>"

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    base_price = db.Column(db.Float, nullable=False)
    item_type = db.Column(db.String(50), nullable=False, default='service')
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    def __repr__(self):
        return f"<Service {self.name} (ID: {self.id}), Price: {self.base_price}, Type: {self.item_type}>"

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dog_id = db.Column(db.Integer, db.ForeignKey('dog.id'), nullable=False)
    appointment_datetime = db.Column(db.DateTime, nullable=False) 
    requested_services_text = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='Scheduled', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    google_event_id = db.Column(db.String(255), nullable=True)
    groomer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    checkout_total_amount = db.Column(db.Float, nullable=True)

    def __repr__(self):
        return f"<Appointment ID: {self.id}, Dog ID: {self.dog_id}, DateTime: {self.appointment_datetime}, Status: {self.status}>"

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    details = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<ActivityLog ID: {self.id}, User ID: {self.user_id}, Action: {self.action}>"

# --- Helper Functions ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def check_initial_setup():
    return User.query.first() is None

def log_activity(action, details=None):
    if hasattr(g, 'user') and g.user:
        try:
            log_entry = ActivityLog(user_id=g.user.id, action=action, details=details)
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error logging activity: {e}", exc_info=True)
    else:
        app.logger.warning(f"Attempted to log activity '{action}' but no user in g.")

def get_shared_google_credentials():
    token_file_path = app.config.get('SHARED_TOKEN_FILE', os.path.join(PERSISTENT_DATA_ROOT, 'shared_google_token.json'))
    if not os.path.exists(token_file_path):
        app.logger.info(f"Shared Google token file not found: {token_file_path}")
        return None
    try:
        credentials = Credentials.from_authorized_user_file(token_file_path, GOOGLE_SCOPES)
        if credentials and credentials.expired and credentials.refresh_token:
            app.logger.info("Shared Google credentials expired, attempting refresh...")
            try:
                credentials.refresh(google.auth.transport.requests.Request())
                with open(token_file_path, 'w') as token_file: 
                    token_file.write(credentials.to_json())
                app.logger.info("Shared Google credentials refreshed and saved.")
            except Exception as refresh_err:
                app.logger.error(f"Error refreshing shared Google token: {refresh_err}", exc_info=True)
                return None
        if credentials and credentials.valid:
            return credentials
        else:
            app.logger.warning("Shared Google credentials are not valid after load/refresh attempt.")
            return None
    except Exception as e:
        app.logger.error(f"Unexpected error in get_shared_google_credentials: {e}", exc_info=True)
        return None

# --- Context Processors ---
@app.context_processor
def inject_utilities():
    shared_creds = get_shared_google_credentials()
    is_google_connected = bool(shared_creds and shared_creds.valid)
    return {
        'now': lambda: datetime.datetime.now(timezone.utc),
        'check_initial_setup': check_initial_setup,
        'is_google_calendar_connected': is_google_connected,
        'BUSINESS_TIMEZONE_NAME': BUSINESS_TIMEZONE_NAME,
        'BUSINESS_TIMEZONE': BUSINESS_TIMEZONE,
        'tz': tz,
        'local_datetime': lambda dt_utc: dt_utc.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE) if dt_utc else None,
        'today_date_iso': datetime.datetime.now(BUSINESS_TIMEZONE).strftime('%Y-%m-%d')
    }

# --- Decorators ---
from functools import wraps
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, 'user') or g.user is None:
            flash("You need to be logged in to view this page.", "warning")
            return redirect(url_for('auth_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not g.user.is_admin:
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- Request Hooks ---
@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    g.user = User.query.get(user_id) if user_id else None
    if user_id and not g.user:
        session.pop('user_id', None)
        app.logger.warning(f"User ID {user_id} in session but not in DB. Cleared session.")

# --- Route for serving persistent uploads ---
@app.route('/persistent_uploads/<path:filename>')
@login_required 
def uploaded_persistent_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- Core Routes ---
@app.route('/')
def index():
    if check_initial_setup(): return redirect(url_for('initial_setup'))
    if g.user is None: return redirect(url_for('auth_login'))
    log_activity("Viewed Dashboard")
    upcoming_appointments = []
    try:
        now_utc = datetime.datetime.now(timezone.utc)
        upcoming_appointments = Appointment.query.options(
            db.joinedload(Appointment.dog).joinedload(Dog.owner),
            db.joinedload(Appointment.groomer)
        ).filter(
            Appointment.appointment_datetime >= now_utc,
            Appointment.status == 'Scheduled' 
        ).order_by(Appointment.appointment_datetime.asc()).limit(5).all()
    except Exception as e:
        app.logger.error(f"Error fetching dashboard appointments: {e}", exc_info=True)
        flash("Could not load upcoming appointments.", "warning")
    return render_template('dashboard.html', upcoming_appointments=upcoming_appointments, username=g.user.username)

@app.route('/initial_setup', methods=['GET', 'POST'])
def initial_setup():
    if not check_initial_setup():
        flash("Initial setup already completed.", "info"); return redirect(url_for('auth_login'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        errors = False
        if not username: flash("Username required.", "danger"); errors = True
        if not password: flash("Password required.", "danger"); errors = True
        if password != confirm_password: flash("Passwords do not match.", "danger"); errors = True
        if len(password) < 8 and password: flash("Password too short (min 8 chars).", "danger"); errors = True
        if errors: return render_template('initial_setup.html'), 400
        admin_user = User(username=username, is_admin=True, is_groomer=True) 
        admin_user.set_password(password)
        try:
            db.session.add(admin_user); db.session.commit()
            created_user = User.query.filter_by(username=username).first()
            if created_user:
                setup_log = ActivityLog(user_id=created_user.id, action="Initial admin account created", details=f"Username: {username}")
                db.session.add(setup_log); db.session.commit()
            flash("Admin account created! Please log in.", "success")
            return redirect(url_for('auth_login'))
        except IntegrityError:
            db.session.rollback(); flash("Username taken (IntegrityError).", "danger")
            app.logger.error("IntegrityError during initial_setup.")
            return render_template('initial_setup.html'), 500
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error initial setup: {e}", exc_info=True)
            flash("Error during setup.", "danger")
            return render_template('initial_setup.html'), 500
    return render_template('initial_setup.html')

@app.route('/login', methods=['GET', 'POST'], endpoint='auth_login')
def login():
    if check_initial_setup(): flash("Please complete initial setup.", "warning"); return redirect(url_for('initial_setup'))
    if g.user: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash("Username and password required.", "danger"); return render_template('login.html'), 400
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session.clear(); session['user_id'] = user.id; session.permanent = True
            g.user = user
            log_activity("Logged in")
            flash(f"Welcome back, {user.username}!", "success")
            next_page = request.args.get('next')
            if next_page and not (next_page.startswith('/') or next_page.startswith(request.host_url)):
                app.logger.warning(f"Invalid 'next' URL: {next_page}"); next_page = None
            return redirect(next_page or url_for('index'))
        else:
            flash("Invalid username or password.", "danger"); return render_template('login.html'), 401
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    log_activity("Logged out")
    session.pop('user_id', None)
    g.user = None
    flash("Logged out successfully.", "info")
    return redirect(url_for('auth_login'))

# --- Directory Routes (Owners and Dogs) ---
@app.route('/directory')
@login_required
def directory():
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    owners_query = Owner.query.options(db.joinedload(Owner.dogs))
    if search_query:
        log_activity("Searched Directory", details=f"Query: '{search_query}'")
        search_term = f"%{search_query}%"
        owners_query = owners_query.join(Dog, Owner.id == Dog.owner_id, isouter=True).filter(
            or_(Owner.name.ilike(search_term), Owner.phone_number.ilike(search_term),
                Owner.email.ilike(search_term), Dog.name.ilike(search_term))
        ).distinct()
    else:
        log_activity("Viewed Directory page")
    owners_pagination = owners_query.order_by(Owner.name.asc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('directory.html', owners=owners_pagination.items, pagination=owners_pagination, search_query=search_query)

@app.route('/add_owner', methods=['GET', 'POST'])
@login_required
def add_owner():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip().lower()
        address = request.form.get('address', '').strip()
        errors = {}
        if not name: errors['name'] = "Owner Name required."
        if not phone: errors['phone'] = "Phone Number required."
        if Owner.query.filter_by(phone_number=phone).first(): errors['phone_conflict'] = f"Phone '{phone}' already exists."
        if email and Owner.query.filter_by(email=email).first(): errors['email_conflict'] = f"Email '{email}' already exists."
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            return render_template('add_owner.html', owner=request.form.to_dict()), 400
        new_owner = Owner(name=name, phone_number=phone, email=email or None, address=address or None, created_by_user_id=g.user.id)
        try:
            db.session.add(new_owner); db.session.commit()
            log_activity("Added Owner", details=f"Name: {name}, Phone: {phone}")
            flash(f"Owner '{name}' added!", "success"); return redirect(url_for('directory'))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error adding owner: {e}", exc_info=True)
            flash("Error adding owner.", "danger"); return render_template('add_owner.html', owner=request.form.to_dict()), 500
    log_activity("Viewed Add Owner page")
    return render_template('add_owner.html', owner={})

@app.route('/owner/<int:owner_id>')
@login_required
def view_owner(owner_id):
    owner = Owner.query.options(
        db.joinedload(Owner.dogs) 
    ).get_or_404(owner_id)
    log_activity("Viewed Owner Profile", details=f"Owner: {owner.name} (ID: {owner_id})")
    return render_template('owner_profile.html', owner=owner)

@app.route('/owner/<int:owner_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_owner(owner_id):
    owner_to_edit = Owner.query.get_or_404(owner_id)
    if request.method == 'POST':
        original_phone = owner_to_edit.phone_number
        original_email = owner_to_edit.email
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip().lower()
        address = request.form.get('address', '').strip()
        errors = {}
        if not name: errors['name'] = "Owner Name required."
        if not phone: errors['phone'] = "Phone Number required."
        if phone != original_phone and Owner.query.filter(Owner.id != owner_id, Owner.phone_number == phone).first():
            errors['phone_conflict'] = f"Phone '{phone}' already exists."
        if email and email != original_email and Owner.query.filter(Owner.id != owner_id, Owner.email == email).first():
            errors['email_conflict'] = f"Email '{email}' already exists."
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = {'id': owner_id, 'name': name, 'phone_number': phone, 'email': email, 'address': address}
            return render_template('edit_owner.html', owner=form_data), 400
        owner_to_edit.name = name; owner_to_edit.phone_number = phone
        owner_to_edit.email = email or None; owner_to_edit.address = address or None
        try:
            db.session.commit()
            log_activity("Edited Owner", details=f"Owner ID: {owner_id}, Name: {name}")
            flash(f"Owner '{name}' updated!", "success"); return redirect(url_for('view_owner', owner_id=owner_id))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error editing owner {owner_id}: {e}", exc_info=True)
            flash("Error updating owner.", "danger"); return render_template('edit_owner.html', owner=owner_to_edit), 500
    log_activity("Viewed Edit Owner page", details=f"Owner ID: {owner_id}")
    return render_template('edit_owner.html', owner=owner_to_edit)

# --- Dog Routes ---
def _handle_dog_picture_upload(dog_instance, request_files):
    if 'dog_picture' not in request_files: return None
    file = request_files['dog_picture']
    if file and file.filename != '' and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        new_filename = secure_filename(f"dog_{dog_instance.id or 'temp'}_{uuid.uuid4().hex[:8]}.{ext}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename) 
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        if dog_instance.picture_filename and dog_instance.picture_filename != new_filename:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], dog_instance.picture_filename)
            if os.path.exists(old_path):
                try: os.remove(old_path); app.logger.info(f"Deleted old dog pic: {old_path}")
                except OSError as e_rem: app.logger.error(f"Error deleting old dog pic {old_path}: {e_rem}")
        try:
            file.save(file_path); app.logger.info(f"Saved new dog pic: {file_path}"); return new_filename
        except Exception as e_save:
            flash(f"Failed to save picture: {e_save}", "warning")
            app.logger.error(f"Failed to save dog pic {file_path}: {e_save}", exc_info=True)
    elif file and file.filename != '': flash("Invalid file type for dog picture.", "warning")
    return None

@app.route('/owner/<int:owner_id>/add_dog', methods=['GET', 'POST'])
@login_required
def add_dog(owner_id):
    owner = Owner.query.get_or_404(owner_id)
    if request.method == 'POST':
        dog_name = request.form.get('dog_name', '').strip()
        if not dog_name: flash("Dog Name required.", "danger"); return render_template('add_dog.html', owner=owner, dog=request.form.to_dict()), 400
        new_dog = Dog(
            name=dog_name, breed=(request.form.get('breed', '').strip() or None),
            birthday=(request.form.get('birthday', '').strip() or None),
            temperament=(request.form.get('temperament', '').strip() or None),
            hair_style_notes=(request.form.get('hair_style_notes', '').strip() or None),
            aggression_issues=(request.form.get('aggression_issues', '').strip() or None),
            anxiety_issues=(request.form.get('anxiety_issues', '').strip() or None),
            other_notes=(request.form.get('other_notes', '').strip() or None),
            owner_id=owner.id, created_by_user_id=g.user.id
        )
        try:
            db.session.add(new_dog); db.session.flush()
            uploaded_filename = _handle_dog_picture_upload(new_dog, request.files)
            if uploaded_filename: new_dog.picture_filename = uploaded_filename
            db.session.commit()
            log_activity("Added Dog", details=f"Name: {dog_name}, Owner: {owner.name}")
            flash(f"Dog '{dog_name}' added for {owner.name}!", "success"); return redirect(url_for('view_owner', owner_id=owner.id))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error adding dog: {e}", exc_info=True)
            flash("Error adding dog.", "danger"); return render_template('add_dog.html', owner=owner, dog=request.form.to_dict()), 500
    log_activity("Viewed Add Dog page", details=f"For Owner: {owner.name}")
    return render_template('add_dog.html', owner=owner, dog={})

@app.route('/dog/<int:dog_id>')
@login_required
def view_dog(dog_id):
    dog = Dog.query.options(
        db.joinedload(Dog.owner) 
    ).get_or_404(dog_id)
    appointments_for_dog = dog.appointments.options(db.joinedload(Appointment.groomer)).all()
    log_activity("Viewed Dog Profile", details=f"Dog: {dog.name}")
    return render_template('dog_profile.html', dog=dog, appointments=appointments_for_dog)

@app.route('/dog/<int:dog_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_dog(dog_id):
    dog = Dog.query.options(db.joinedload(Dog.owner)).get_or_404(dog_id)
    if request.method == 'POST':
        dog_name = request.form.get('dog_name', '').strip()
        if not dog_name: flash("Dog Name required.", "danger"); return render_template('edit_dog.html', dog=dog), 400
        dog.name = dog_name
        dog.breed = request.form.get('breed', '').strip() or None
        dog.birthday = request.form.get('birthday', '').strip() or None
        dog.temperament = request.form.get('temperament', '').strip() or None
        dog.hair_style_notes = request.form.get('hair_style_notes', '').strip() or None
        dog.aggression_issues = request.form.get('aggression_issues', '').strip() or None
        dog.anxiety_issues = request.form.get('anxiety_issues', '').strip() or None
        dog.other_notes = request.form.get('other_notes', '').strip() or None
        try:
            uploaded_filename = _handle_dog_picture_upload(dog, request.files)
            if uploaded_filename: dog.picture_filename = uploaded_filename
            db.session.commit()
            log_activity("Edited Dog Profile", details=f"Dog: {dog_name}")
            flash(f"Profile for '{dog_name}' updated!", "success"); return redirect(url_for('view_dog', dog_id=dog.id))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error updating dog {dog_id}: {e}", exc_info=True)
            flash("Error updating dog profile.", "danger")
            current_data = dog; current_data.name = dog_name
            return render_template('edit_dog.html', dog=current_data), 500
    log_activity("Viewed Edit Dog page", details=f"Dog: {dog.name}")
    return render_template('edit_dog.html', dog=dog)

@app.route('/dog/<int:dog_id>/delete', methods=['POST'])
@login_required
def delete_dog(dog_id):
    dog_to_delete = Dog.query.get_or_404(dog_id)
    dog_name = dog_to_delete.name; owner_id = dog_to_delete.owner_id
    pic_to_delete = dog_to_delete.picture_filename
    try:
        db.session.delete(dog_to_delete); db.session.commit()
        if pic_to_delete:
            path = os.path.join(app.config['UPLOAD_FOLDER'], pic_to_delete)
            if os.path.exists(path):
                try: os.remove(path); app.logger.info(f"Deleted dog pic: {path}")
                except OSError as e_rem: app.logger.error(f"Error deleting dog pic file {path}: {e_rem}")
        log_activity("Deleted Dog", details=f"Dog: {dog_name}")
        flash(f"Dog '{dog_name}' deleted.", "success"); return redirect(url_for('view_owner', owner_id=owner_id))
    except Exception as e:
        db.session.rollback(); app.logger.error(f"Error deleting dog '{dog_name}': {e}", exc_info=True)
        flash(f"Error deleting '{dog_name}'.", "danger"); return redirect(url_for('view_dog', dog_id=dog_id))

# --- Management Routes (Admin Only) ---
@app.route('/management')
@admin_required
def management():
    log_activity("Viewed Management page")
    return render_template('management.html')

def _handle_user_picture_upload(user_instance, request_files):
    if 'user_picture' not in request_files: return None
    file = request_files['user_picture']
    if file and file.filename != '' and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        new_filename = secure_filename(f"user_{user_instance.id or 'temp'}_{uuid.uuid4().hex[:8]}.{ext}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        if user_instance.picture_filename and user_instance.picture_filename != new_filename:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], user_instance.picture_filename)
            if os.path.exists(old_path):
                try: os.remove(old_path); app.logger.info(f"Deleted old user pic: {old_path}")
                except OSError as e_rem: app.logger.error(f"Could not delete old user pic {old_path}: {e_rem}")
        try:
            file.save(file_path); app.logger.info(f"Saved new user pic: {file_path}"); return new_filename
        except Exception as e_save:
            flash(f"Failed to save user picture: {e_save}", "warning")
            app.logger.error(f"Failed to save user pic {file_path}: {e_save}", exc_info=True)
    elif file and file.filename != '': flash("Invalid file type for user picture.", "warning")
    return None

@app.route('/manage/users')
@admin_required
def manage_users():
    log_activity("Viewed User Management page")
    users = User.query.order_by(User.username).all()
    return render_template('manage_users.html', users=users)

@app.route('/manage/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        is_admin = 'is_admin' in request.form
        is_groomer = 'is_groomer' in request.form 
        errors = {}
        if not username: errors['username'] = "Username required."
        if not password: errors['password'] = "Password required."
        if password != confirm_password: errors['password_confirm'] = "Passwords do not match."
        if len(password) < 8 and password: errors['password_length'] = "Password too short."
        if User.query.filter_by(username=username).first(): errors['username_conflict'] = "Username exists."
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict()
            form_data['is_admin'] = is_admin; form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='add', user_data=form_data), 400
        new_user = User(username=username, is_admin=is_admin, is_groomer=is_groomer)
        new_user.set_password(password)
        try:
            db.session.add(new_user); db.session.flush()
            uploaded_filename = _handle_user_picture_upload(new_user, request.files)
            if uploaded_filename: new_user.picture_filename = uploaded_filename
            db.session.commit()
            log_activity("Added User", details=f"Username: {username}, Admin: {is_admin}, Groomer: {is_groomer}")
            flash(f"User '{username}' added.", "success"); return redirect(url_for('manage_users'))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error adding user: {e}", exc_info=True)
            flash("Error adding user.", "danger")
            form_data = request.form.to_dict()
            form_data['is_admin'] = is_admin; form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='add', user_data=form_data), 500
    log_activity("Viewed Add User page")
    return render_template('user_form.html', mode='add', user_data={'is_groomer': True}) 

@app.route('/manage/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user_to_edit = User.query.get_or_404(user_id)
    if request.method == 'POST':
        original_username = user_to_edit.username
        new_username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        is_admin = 'is_admin' in request.form
        is_groomer = 'is_groomer' in request.form
        errors = {}
        if not new_username: errors['username'] = "Username required."
        if new_username != original_username and User.query.filter(User.id != user_id, User.username == new_username).first():
            errors['username_conflict'] = "Username taken."
        password_changed = False
        if password:
            if password != confirm_password: errors['password_confirm'] = "Passwords do not match."
            if len(password) < 8: errors['password_length'] = "Password too short."
            else: password_changed = True
        if user_to_edit.is_admin and not is_admin: 
            admin_count = User.query.filter_by(is_admin=True).count()
            if admin_count <= 1: 
                errors['last_admin'] = "Cannot remove admin status from the last administrator."
                is_admin = True 
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict(); 
            form_data['id'] = user_id; form_data['picture_filename'] = user_to_edit.picture_filename
            form_data['is_admin'] = is_admin; form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='edit', user_data=form_data), 400
        user_to_edit.username = new_username
        if password_changed: user_to_edit.set_password(password)
        user_to_edit.is_admin = is_admin
        user_to_edit.is_groomer = is_groomer
        try:
            uploaded_filename = _handle_user_picture_upload(user_to_edit, request.files)
            if uploaded_filename: user_to_edit.picture_filename = uploaded_filename
            db.session.commit()
            log_activity("Edited User", details=f"User ID: {user_id}, Username: {new_username}, Admin: {is_admin}, Groomer: {is_groomer}")
            flash(f"User '{new_username}' updated.", "success"); return redirect(url_for('manage_users'))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error updating user {user_id}: {e}", exc_info=True)
            flash("Error updating user.", "danger")
            form_data = request.form.to_dict(); form_data['id'] = user_id; form_data['picture_filename'] = user_to_edit.picture_filename
            form_data['is_admin'] = is_admin; form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='edit', user_data=form_data), 500
    log_activity("Viewed Edit User page", details=f"User ID: {user_id}")
    return render_template('user_form.html', mode='edit', user_data=user_to_edit) 

@app.route('/manage/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.id == g.user.id:
        flash("Cannot delete own account.", "danger"); return redirect(url_for('manage_users'))
    if user_to_delete.is_admin and User.query.filter_by(is_admin=True).count() <= 1:
        flash("Cannot delete last admin.", "danger"); return redirect(url_for('manage_users'))
    username_deleted = user_to_delete.username
    pic_to_delete = user_to_delete.picture_filename
    try:
        Appointment.query.filter_by(groomer_id=user_id).update({'groomer_id': None})
        db.session.delete(user_to_delete); db.session.commit()
        if pic_to_delete:
            path = os.path.join(app.config['UPLOAD_FOLDER'], pic_to_delete)
            if os.path.exists(path):
                try: os.remove(path); app.logger.info(f"Deleted user pic: {path}")
                except OSError as e_rem: app.logger.error(f"Error deleting user pic file {path}: {e_rem}")
        log_activity("Deleted User", details=f"Username: {username_deleted}")
        flash(f"User '{username_deleted}' deleted.", "success")
    except IntegrityError as ie:
        db.session.rollback(); app.logger.error(f"IntegrityError deleting user '{username_deleted}': {ie}", exc_info=True)
        flash(f"Could not delete '{username_deleted}'. Associated records might exist.", "danger")
    except Exception as e:
        db.session.rollback(); app.logger.error(f"Error deleting user '{username_deleted}': {e}", exc_info=True)
        flash(f"Error deleting '{username_deleted}'.", "danger")
    return redirect(url_for('manage_users'))

@app.route('/manage/services')
@admin_required
def manage_services():
    log_activity("Viewed Service/Fee Management page")
    all_items = Service.query.order_by(Service.item_type, Service.name).all()
    services = [item for item in all_items if item.item_type == 'service']
    fees = [item for item in all_items if item.item_type == 'fee']
    return render_template('manage_services.html', services=services, fees=fees)

@app.route('/manage/services/add', methods=['GET', 'POST'])
@admin_required
def add_service():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price_str = request.form.get('base_price', '').strip()
        item_type = request.form.get('item_type', 'service').strip()
        errors = {}
        if not name: errors['name'] = "Item Name required."
        if not price_str: errors['base_price'] = "Base Price required."
        if item_type not in ['service', 'fee']: errors['item_type_invalid'] = "Invalid item type."
        price = None
        try:
            price = Decimal(price_str)
            if price < Decimal('0.00'): errors['base_price_negative'] = "Price cannot be negative."
        except InvalidOperation:
            if 'base_price' not in errors: errors['base_price_invalid'] = "Invalid price format."
        if Service.query.filter_by(name=name).first(): errors['name_conflict'] = f"Item '{name}' already exists."
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            return render_template('service_form.html', mode='add', item_data=request.form.to_dict()), 400
        new_item = Service(name=name, description=description or None, base_price=float(price), item_type=item_type, created_by_user_id=g.user.id)
        try:
            db.session.add(new_item); db.session.commit()
            log_activity(f"Added {item_type.capitalize()}", details=f"Name: {name}, Price: {price:.2f}")
            flash(f"{item_type.capitalize()} '{name}' added.", "success"); return redirect(url_for('manage_services'))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error adding {item_type}: {e}", exc_info=True)
            flash(f"Error adding {item_type}.", "danger"); return render_template('service_form.html', mode='add', item_data=request.form.to_dict()), 500
    log_activity("Viewed Add Service/Fee page")
    return render_template('service_form.html', mode='add', item_data={})

@app.route('/manage/services/<int:service_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_service(service_id):
    item_to_edit = Service.query.get_or_404(service_id)
    if request.method == 'POST':
        original_name = item_to_edit.name
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price_str = request.form.get('base_price', '').strip()
        item_type = request.form.get('item_type', 'service').strip()
        errors = {}
        if not name: errors['name'] = "Item Name required."
        price = None
        try:
            price = Decimal(price_str)
            if price < Decimal('0.00'): errors['base_price_negative'] = "Price cannot be negative."
        except InvalidOperation: errors['base_price_invalid'] = "Invalid price format."
        if name != original_name and Service.query.filter(Service.id != service_id, Service.name == name).first():
            errors['name_conflict'] = f"Another item named '{name}' already exists."
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict(); form_data['id'] = service_id
            return render_template('service_form.html', mode='edit', item_data=form_data), 400
        item_to_edit.name = name; item_to_edit.description = description or None
        item_to_edit.base_price = float(price); item_to_edit.item_type = item_type
        try:
            db.session.commit()
            log_activity(f"Edited {item_type.capitalize()}", details=f"ID: {service_id}, Name: {name}")
            flash(f"{item_type.capitalize()} '{name}' updated.", "success"); return redirect(url_for('manage_services'))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error editing item {service_id}: {e}", exc_info=True)
            flash(f"Error updating {item_type}.", "danger")
            form_data = request.form.to_dict(); form_data['id'] = service_id
            return render_template('service_form.html', mode='edit', item_data=form_data), 500
    log_activity(f"Viewed Edit {item_to_edit.item_type.capitalize()} page", details=f"ID: {service_id}")
    return render_template('service_form.html', mode='edit', item_data=item_to_edit)

@app.route('/manage/services/<int:service_id>/delete', methods=['POST'])
@admin_required
def delete_service(service_id):
    item_to_delete = Service.query.get_or_404(service_id)
    item_name = item_to_delete.name; item_type = item_to_delete.item_type
    try:
        db.session.delete(item_to_delete); db.session.commit()
        log_activity(f"Deleted {item_type.capitalize()}", details=f"ID: {service_id}, Name: {item_name}")
        flash(f"{item_type.capitalize()} '{item_name}' deleted.", "success")
    except Exception as e:
        db.session.rollback(); app.logger.error(f"Error deleting {item_type} '{item_name}': {e}", exc_info=True)
        flash(f"Error deleting '{item_name}'. It might be in use.", "danger")
    return redirect(url_for('manage_services'))

# --- Checkout Route (MODIFIED to save checkout_total_amount) ---
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    scheduled_appointments = Appointment.query.filter_by(status='Scheduled')\
                                .options(db.joinedload(Appointment.dog).joinedload(Dog.owner),
                                         db.joinedload(Appointment.groomer))\
                                .order_by(Appointment.appointment_datetime.asc()).all()
    all_services_db = Service.query.order_by(Service.name).all()
    all_services = [s for s in all_services_db if s.item_type == 'service']
    all_fees = [s for s in all_services_db if s.item_type == 'fee']

    calculated_data = None
    selected_appointment_id_str = request.form.get('appointment_id') if request.method == 'POST' else request.args.get('appointment_id')
    selected_appointment_id = None
    if selected_appointment_id_str:
        try: selected_appointment_id = int(selected_appointment_id_str)
        except ValueError: flash("Invalid appointment ID format.", "danger"); selected_appointment_id = None

    current_selected_item_ids = []
    appointment_to_checkout = None

    if selected_appointment_id:
        appointment_to_checkout = Appointment.query.options(
            db.joinedload(Appointment.dog).joinedload(Dog.owner),
            db.joinedload(Appointment.groomer)
        ).get(selected_appointment_id)
        if not appointment_to_checkout:
            flash(f"Appointment ID {selected_appointment_id} not found.", "warning"); selected_appointment_id = None
        elif appointment_to_checkout.status != 'Scheduled' and request.method == 'GET':
             flash(f"Note: Appt for {appointment_to_checkout.dog.name} is '{appointment_to_checkout.status}'. Checkout marks as 'Completed'.", "info")

    if request.method == 'POST':
        action = request.form.get('action')
        if not selected_appointment_id or not appointment_to_checkout:
            flash("Please select a valid appointment.", "danger")
            return render_template('checkout.html', scheduled_appointments=scheduled_appointments, all_services=all_services, all_fees=all_fees, selected_appointment_id=None, selected_item_ids=[]), 400

        selected_service_ids_str = request.form.getlist('service_ids')
        selected_fee_ids_str = request.form.getlist('fee_ids')
        combined_ids_str = selected_service_ids_str + selected_fee_ids_str
        try: current_selected_item_ids = [int(sid) for sid in combined_ids_str]
        except ValueError: flash("Invalid service/fee ID.", "danger"); current_selected_item_ids = []

        if not current_selected_item_ids and action in ["calculate_total", "complete_checkout"]:
            flash("Please select at least one service or fee.", "warning")
        else:
            items_for_this_checkout = Service.query.filter(Service.id.in_(current_selected_item_ids)).all()
            if not items_for_this_checkout and action in ["calculate_total", "complete_checkout"]:
                flash("No valid services/fees found for selection.", "warning")
            else:
                subtotal = sum(Decimal(str(item.base_price)) for item in items_for_this_checkout)
                total = subtotal

                calculated_data = {
                    'appointment': appointment_to_checkout, 'dog': appointment_to_checkout.dog,
                    'owner': appointment_to_checkout.dog.owner, 'billed_items': items_for_this_checkout,
                    'subtotal': subtotal, 'total': total
                }
                log_activity("Calculated Checkout Total", details=f"Appt ID: {appointment_to_checkout.id}, Total: ${total:.2f}")

                if action == "complete_checkout":
                    if appointment_to_checkout.status != "Scheduled":
                        flash(f"Appt for {appointment_to_checkout.dog.name} is already '{appointment_to_checkout.status}'.", "warning")
                    else:
                        appointment_to_checkout.status = "Completed"
                        final_item_names = ", ".join(sorted([item.name for item in items_for_this_checkout]))
                        appointment_to_checkout.requested_services_text = final_item_names if final_item_names else "N/A"
                        appointment_to_checkout.checkout_total_amount = float(total) 
                        try:
                            db.session.commit()
                            log_activity("Completed Checkout", details=f"Appt ID: {appointment_to_checkout.id}, Final Total: ${total:.2f}")
                            flash(f"Checkout for {appointment_to_checkout.dog.name} completed! Total: ${total:.2f}", "success")
                            _sync_appointment_to_google_calendar(appointment_to_checkout, event_type='update')
                            return redirect(url_for('index'))
                        except Exception as e:
                            db.session.rollback(); app.logger.error(f"Error completing checkout for Appt ID {appointment_to_checkout.id}: {e}", exc_info=True)
                            flash("Error finalizing checkout.", "danger")
    
    return render_template('checkout.html',
                           scheduled_appointments=scheduled_appointments, all_services=all_services, all_fees=all_fees,
                           calculated_data=calculated_data, selected_appointment_id=selected_appointment_id,
                           selected_item_ids=current_selected_item_ids, appointment_to_checkout=appointment_to_checkout)

# --- Sales Reports Routes ---
def get_date_range(range_type, start_date_str=None, end_date_str=None):
    today_local = datetime.datetime.now(BUSINESS_TIMEZONE).date()
    start_local, end_local = None, None
    period_display = "Invalid Range"
    if range_type == 'today':
        start_local = datetime.datetime.combine(today_local, datetime.time.min, tzinfo=BUSINESS_TIMEZONE)
        end_local = datetime.datetime.combine(today_local, datetime.time.max, tzinfo=BUSINESS_TIMEZONE)
        period_display = f"Today, {start_local.strftime('%B %d, %Y')}"
    elif range_type == 'this_week':
        start_of_week_local_date = today_local - timedelta(days=today_local.weekday())
        end_of_week_local_date = start_of_week_local_date + timedelta(days=6)
        start_local = datetime.datetime.combine(start_of_week_local_date, datetime.time.min, tzinfo=BUSINESS_TIMEZONE)
        end_local = datetime.datetime.combine(end_of_week_local_date, datetime.time.max, tzinfo=BUSINESS_TIMEZONE)
        period_display = f"This Week: {start_local.strftime('%b %d')} - {end_local.strftime('%b %d, %Y')}"
    elif range_type == 'this_month':
        start_of_month_local_date = today_local.replace(day=1)
        _, num_days_in_month = calendar.monthrange(today_local.year, today_local.month)
        end_of_month_local_date = today_local.replace(day=num_days_in_month)
        start_local = datetime.datetime.combine(start_of_month_local_date, datetime.time.min, tzinfo=BUSINESS_TIMEZONE)
        end_local = datetime.datetime.combine(end_of_month_local_date, datetime.time.max, tzinfo=BUSINESS_TIMEZONE)
        period_display = f"This Month: {start_local.strftime('%B %Y')}"
    elif range_type == 'custom':
        try:
            if not start_date_str or not end_date_str:
                flash("Both start and end dates are required for a custom range.", "danger")
                return None, None, "Error: Incomplete Custom Dates"
            start_local_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_local_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if start_local_date > end_local_date:
                flash("Start date cannot be after end date.", "danger")
                return None, None, "Error: Invalid Custom Date Order"
            start_local = datetime.datetime.combine(start_local_date, datetime.time.min, tzinfo=BUSINESS_TIMEZONE)
            end_local = datetime.datetime.combine(end_local_date, datetime.time.max, tzinfo=BUSINESS_TIMEZONE)
            period_display = f"Custom: {start_local.strftime('%b %d, %Y')} - {end_local.strftime('%b %d, %Y')}"
        except ValueError:
            flash("Invalid custom date format. Please use YYYY-MM-DD.", "danger")
            return None, None, "Error: Invalid Date Format"
    else:
        flash("Unknown date range type selected.", "danger")
        return None, None, "Error: Unknown Date Range"
    if start_local and end_local:
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        return start_utc, end_utc, period_display
    return None, None, period_display

@app.route('/manage/reports', methods=['GET', 'POST'])
@admin_required
def view_sales_reports():
    all_groomers_for_dropdown = User.query.filter_by(is_groomer=True).order_by(User.username).all()
    report_data_processed = None
    report_period_display = "Report Not Yet Generated"
    selected_groomer_name_display = "All Groomers"

    if request.method == 'POST':
        log_activity("Sales Report Generation Attempt")
        date_range_type = request.form.get('date_range_type', 'today')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        groomer_id_str = request.form.get('groomer_id')

        start_utc, end_utc, report_period_display = get_date_range(date_range_type, start_date_str, end_date_str)

        if not start_utc or not end_utc:
            return render_template('reports_form.html', all_groomers=all_groomers_for_dropdown, report_period_display=report_period_display)

        query = Appointment.query.filter(
            Appointment.status == 'Completed',
            Appointment.appointment_datetime >= start_utc,
            Appointment.appointment_datetime <= end_utc
        ).options(db.joinedload(Appointment.groomer))

        if groomer_id_str:
            try:
                selected_groomer_id = int(groomer_id_str)
                query = query.filter(Appointment.groomer_id == selected_groomer_id)
                selected_groomer_user = User.query.get(selected_groomer_id)
                selected_groomer_name_display = selected_groomer_user.username if selected_groomer_user else "Unknown Groomer"
            except ValueError:
                flash("Invalid Groomer ID.", "warning")

        completed_appointments_in_range = query.all()
        groomer_specific_reports = {}
        store_wide_summary = {'items_sold': {}, 'grand_total': Decimal('0.0')}
        all_services_from_db = Service.query.all()
        service_prices_map = {s.name: Decimal(str(s.base_price)) for s in all_services_from_db}

        for appt in completed_appointments_in_range:
            appointment_actual_total = Decimal('0.0')
            if appt.checkout_total_amount is not None:
                try: appointment_actual_total = Decimal(str(appt.checkout_total_amount))
                except InvalidOperation: app.logger.warning(f"Invalid checkout_total_amount for Appt {appt.id}")
            
            if appt.checkout_total_amount is None or appointment_actual_total == Decimal('0.0'):
                recalculated_total = Decimal('0.0')
                if appt.requested_services_text:
                    for service_name in [s.strip() for s in appt.requested_services_text.split(',') if s.strip()]:
                        recalculated_total += service_prices_map.get(service_name, Decimal('0.0'))
                appointment_actual_total = recalculated_total
                if appt.checkout_total_amount is None:
                     app.logger.info(f"Appt {appt.id}: checkout_total_amount was null. Used recalculated ${appointment_actual_total:.2f}")

            current_groomer_id = appt.groomer_id if appt.groomer_id else 0
            current_groomer_name = appt.groomer.username if appt.groomer else "Unassigned"

            if current_groomer_id not in groomer_specific_reports:
                groomer_specific_reports[current_groomer_id] = {
                    'groomer_name': current_groomer_name, 'items_sold': {}, 'total_groomer_sales': Decimal('0.0')
                }
            
            groomer_specific_reports[current_groomer_id]['total_groomer_sales'] += appointment_actual_total
            store_wide_summary['grand_total'] += appointment_actual_total

            if appt.requested_services_text:
                item_names_billed = [s.strip() for s in appt.requested_services_text.split(',') if s.strip()]
                for item_name in item_names_billed:
                    item_price = service_prices_map.get(item_name, Decimal('0.0'))
                    gs_items = groomer_specific_reports[current_groomer_id]['items_sold']
                    if item_name not in gs_items: gs_items[item_name] = {'quantity': 0, 'total_sales': Decimal('0.0')}
                    gs_items[item_name]['quantity'] += 1
                    gs_items[item_name]['total_sales'] += item_price
                    sw_items = store_wide_summary['items_sold']
                    if item_name not in sw_items: sw_items[item_name] = {'quantity': 0, 'total_sales': Decimal('0.0')}
                    sw_items[item_name]['quantity'] += 1
                    sw_items[item_name]['total_sales'] += item_price
        
        report_data_processed = {'groomer_reports': groomer_specific_reports, 'store_summary': store_wide_summary}
        log_activity("Sales Report Generated", details=f"Period: {report_period_display}, Groomer: {selected_groomer_name_display}")
        return render_template('report_display.html', report_data=report_data_processed,
                               report_period_display=report_period_display,
                               selected_groomer_name=selected_groomer_name_display, all_groomers=all_groomers_for_dropdown)

    log_activity("Viewed Sales Report Form")
    return render_template('reports_form.html', all_groomers=all_groomers_for_dropdown, report_period_display=report_period_display)

# --- Calendar and Appointment Routes ---
def _sync_appointment_to_google_calendar(appointment_obj, event_type='create'):
    shared_creds = get_shared_google_credentials()
    if not (shared_creds and shared_creds.valid):
        flash_msg = "Shared Google Calendar not connected. Local changes saved."
        if event_type == 'delete': flash_msg = "Shared Google Calendar not connected. Local appointment deleted."
        flash(flash_msg, "warning"); app.logger.warning(f"GCal sync skipped for Appt ID {appointment_obj.id} (event: {event_type})")
        return
    try:
        gcal_service = build('calendar', 'v3', credentials=shared_creds)
        dog = Dog.query.get(appointment_obj.dog_id)
        owner = Owner.query.get(dog.owner_id) if dog else None
        groomer = User.query.get(appointment_obj.groomer_id) if appointment_obj.groomer_id else None
        if not dog or not owner:
            app.logger.error(f"Cannot sync Appt {appointment_obj.id} to GCal: Missing Dog/Owner info.")
            flash("Could not sync to GCal: Dog or Owner info missing.", "danger"); return
        if event_type == 'delete':
            if appointment_obj.google_event_id:
                try:
                    gcal_service.events().delete(calendarId=SHARED_GOOGLE_CALENDAR_ID, eventId=appointment_obj.google_event_id).execute()
                    log_activity("Synced Appointment Deletion to GCal", details=f"Appt ID: {appointment_obj.id}")
                    flash("Appointment deleted from shared Google Calendar.", "info")
                except HttpError as e:
                    if e.resp.status in [404, 410]: app.logger.info(f"GCal event {appointment_obj.google_event_id} for Appt {appointment_obj.id} not found for deletion.")
                    else: raise
            else: app.logger.info(f"No GCal Event ID for Appt ID {appointment_obj.id} to delete from GCal.")
            return
        utc_start_datetime = appointment_obj.appointment_datetime
        utc_end_datetime = utc_start_datetime + timedelta(hours=1)
        summary_prefix = ""
        if appointment_obj.status == "Completed": summary_prefix = "[COMPLETED] "
        elif appointment_obj.status == "Cancelled": summary_prefix = "[CANCELLED] "
        elif appointment_obj.status == "No Show": summary_prefix = "[NO SHOW] "
        summary = f"{summary_prefix}Grooming: {dog.name} ({owner.name})"
        if groomer: summary += f" - Groomer: {groomer.username}"
        description = (f"Services: {appointment_obj.requested_services_text or 'N/A'}\nNotes: {appointment_obj.notes or 'None'}\n"
                       f"Status: {appointment_obj.status}\nGroomer: {groomer.username if groomer else 'Unassigned'}\n\n"
                       f"Owner: {owner.name}\nPhone: {owner.phone_number}\n{('Email: ' + owner.email) if owner.email else ''}\n\n(Booked via App)")
        event_body = {'summary': summary, 'description': description, 'start': {'dateTime': utc_start_datetime.isoformat(), 'timeZone': 'UTC'}, 'end': {'dateTime': utc_end_datetime.isoformat(), 'timeZone': 'UTC'}}
        if event_type == 'update' and appointment_obj.google_event_id:
            gcal_service.events().update(calendarId=SHARED_GOOGLE_CALENDAR_ID, eventId=appointment_obj.google_event_id, body=event_body).execute()
            log_activity("Synced Appointment Edit to GCal", details=f"Appt ID: {appointment_obj.id}")
            flash("Appointment changes synced to shared Google Calendar.", "info")
        elif event_type == 'create' or (event_type == 'update' and not appointment_obj.google_event_id):
            created_event = gcal_service.events().insert(calendarId=SHARED_GOOGLE_CALENDAR_ID, body=event_body).execute()
            appointment_obj.google_event_id = created_event.get('id'); db.session.commit()
            log_activity("Synced New Appointment to GCal", details=f"Appt ID: {appointment_obj.id}")
            flash("Appointment synced to shared Google Calendar.", "info")
    except HttpError as e_gcal_http:
        err_reason = e_gcal_http.reason if hasattr(e_gcal_http, 'reason') else str(e_gcal_http)
        app.logger.error(f"GCal API HTTP error for Appt {appointment_obj.id} ({event_type}): {err_reason}", exc_info=True)
        flash(f"GCal error: {err_reason}. Local changes saved.", "warning")
    except Exception as e_sync:
        app.logger.error(f"Error syncing appt {appointment_obj.id} ({event_type}) to GCal: {e_sync}", exc_info=True)
        flash(f"Local appt {event_type}d, but GCal sync error: {e_sync}", "warning")

@app.route('/calendar')
@login_required
def calendar_view():
    log_activity("Viewed Calendar page")
    local_appointments = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter(
        Appointment.status == 'Scheduled' 
    ).order_by(Appointment.appointment_datetime.asc()).all()
    return render_template('calendar.html', local_appointments=local_appointments)

@app.route('/api/appointments') 
@login_required
def api_appointments(): 
    start_str = request.args.get('start'); end_str = request.args.get('end')
    try:
        start_dt = dateutil_parser.isoparse(start_str).astimezone(timezone.utc) if start_str else None
        end_dt = dateutil_parser.isoparse(end_str).astimezone(timezone.utc) if end_str else None
    except ValueError: return jsonify({"error": "Invalid date format."}), 400
    
    query = Appointment.query.options(db.joinedload(Appointment.dog).joinedload(Dog.owner), db.joinedload(Appointment.groomer))
    if start_dt and end_dt: 
        query = query.filter(Appointment.appointment_datetime.between(start_dt, end_dt))
    appointments_db = query.order_by(Appointment.appointment_datetime.asc()).all()
    events = []
    for appt in appointments_db:
        title = f"{appt.dog.name} ({appt.dog.owner.name})"
        if appt.groomer: title += f" - {appt.groomer.username}"
        if appt.status != "Scheduled": title = f"[{appt.status.upper()}] {title}"
        
        color_map = {
            "Scheduled": "#007bff", 
            "Completed": "#28a745", 
            "Cancelled": "#6c757d", 
            "No Show": "#dc3545"    
        }
        event_color = color_map.get(appt.status, "#ffc107") 

        events.append({
            "id": appt.id, "title": title, 
            "start": appt.appointment_datetime.isoformat(), 
            "end": (appt.appointment_datetime + timedelta(hours=1)).isoformat(), 
            "allDay": False, "dog_id": appt.dog_id, "dog_name": appt.dog.name, 
            "owner_name": appt.dog.owner.name, 
            "groomer_name": appt.groomer.username if appt.groomer else "Unassigned",
            "status": appt.status, "notes": appt.notes, "services": appt.requested_services_text,
            "url": url_for('edit_appointment', appointment_id=appt.id), 
            "color": event_color,
            "borderColor": event_color 
        })
    return jsonify(events)

@app.route('/add_appointment', methods=['GET', 'POST'])
@login_required
def add_appointment():
    dogs = Dog.query.options(db.joinedload(Dog.owner)).order_by(Dog.name).all()
    groomers_for_dropdown = User.query.filter_by(is_groomer=True).order_by(User.username).all()
    if request.method == 'POST':
        dog_id_str = request.form.get('dog_id'); date_str = request.form.get('appointment_date')
        time_str = request.form.get('appointment_time'); services_text = request.form.get('services_text', '').strip()
        notes = request.form.get('notes', '').strip(); groomer_id_str = request.form.get('groomer_id')
        errors = {}
        if not dog_id_str: errors['dog'] = "Dog required."
        if not date_str: errors['date'] = "Date required."
        if not time_str: errors['time'] = "Time required."
        utc_dt = None; local_dt_for_log = None
        try:
            naive_dt = datetime.datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
            local_dt_for_log = naive_dt.replace(tzinfo=BUSINESS_TIMEZONE) 
            utc_dt = local_dt_for_log.astimezone(timezone.utc)
        except ValueError: errors['datetime_format'] = "Invalid date/time format."
        dog_id = int(dog_id_str) if dog_id_str and dog_id_str.isdigit() else None
        selected_dog = Dog.query.get(dog_id) if dog_id else None
        if not selected_dog: errors['dog_invalid'] = "Dog not found."
        groomer_id = int(groomer_id_str) if groomer_id_str and groomer_id_str.isdigit() else None
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            return render_template('add_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=request.form.to_dict()), 400
        new_appt = Appointment(dog_id=selected_dog.id, appointment_datetime=utc_dt, requested_services_text=services_text or None, notes=notes or None, status='Scheduled', created_by_user_id=g.user.id, groomer_id=groomer_id)
        try:
            db.session.add(new_appt); db.session.commit()
            log_activity("Added Local Appt", details=f"Dog: {selected_dog.name}, Time: {local_dt_for_log.strftime('%Y-%m-%d %I:%M %p %Z') if local_dt_for_log else 'N/A'}")
            flash(f"Appt for {selected_dog.name} scheduled!", "success")
            _sync_appointment_to_google_calendar(new_appt, event_type='create')
            return redirect(url_for('calendar_view'))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error adding appt: {e}", exc_info=True)
            flash("Error adding appointment.", "danger"); return render_template('add_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=request.form.to_dict()), 500
    log_activity("Viewed Add Appointment page")
    return render_template('add_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data={})

@app.route('/appointment/<int:appointment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_appointment(appointment_id):
    appt = Appointment.query.options(db.joinedload(Appointment.dog).joinedload(Dog.owner), db.joinedload(Appointment.groomer)).get_or_404(appointment_id)
    dogs = Dog.query.options(db.joinedload(Dog.owner)).order_by(Dog.name).all()
    groomers_for_dropdown = User.query.filter_by(is_groomer=True).order_by(User.username).all()
    if request.method == 'POST':
        dog_id_str = request.form.get('dog_id'); date_str = request.form.get('appointment_date')
        time_str = request.form.get('appointment_time'); services_text = request.form.get('services_text', '').strip()
        notes = request.form.get('notes', '').strip(); status = request.form.get('status', 'Scheduled').strip()
        groomer_id_str = request.form.get('groomer_id'); errors = {}
        if status not in ['Scheduled', 'Completed', 'Cancelled', 'No Show']: errors['status'] = "Invalid status."
        utc_dt = None; local_dt_for_log = None 
        try:
            naive_dt = datetime.datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
            local_dt_for_log = naive_dt.replace(tzinfo=BUSINESS_TIMEZONE)
            utc_dt = local_dt_for_log.astimezone(timezone.utc)
        except ValueError: errors['datetime_format'] = "Invalid date/time format."
        dog_id = int(dog_id_str) if dog_id_str and dog_id_str.isdigit() else None
        selected_dog = Dog.query.get(dog_id) if dog_id else None
        if not selected_dog: errors['dog_invalid'] = "Dog not found."
        groomer_id = int(groomer_id_str) if groomer_id_str and groomer_id_str.isdigit() else None
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict(); form_data.update({'id': appointment_id, 'dog': appt.dog, 'groomer': appt.groomer})
            return render_template('edit_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=form_data, appointment_id=appointment_id), 400
        appt.dog_id = selected_dog.id if selected_dog else appt.dog_id
        appt.appointment_datetime = utc_dt if utc_dt else appt.appointment_datetime
        appt.requested_services_text = services_text or None; appt.notes = notes or None
        appt.status = status; appt.groomer_id = groomer_id
        try:
            db.session.commit()
            log_activity("Edited Local Appt", details=f"Appt ID: {appointment_id}, Status: {status}, Time: {local_dt_for_log.strftime('%Y-%m-%d %I:%M %p %Z') if local_dt_for_log else 'N/A'}")
            flash(f"Appt for {selected_dog.name if selected_dog else appt.dog.name} updated!", "success")
            _sync_appointment_to_google_calendar(appt, event_type='update')
            return redirect(url_for('calendar_view'))
        except Exception as e:
            db.session.rollback(); app.logger.error(f"Error editing appt {appointment_id}: {e}", exc_info=True)
            flash("Error editing appointment.", "danger")
            form_data = request.form.to_dict(); form_data.update({'id': appointment_id, 'dog': appt.dog, 'groomer': appt.groomer})
            return render_template('edit_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=form_data, appointment_id=appointment_id), 500
    local_dt_form = appt.appointment_datetime.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
    form_data = {'id': appt.id, 'dog_id': appt.dog_id, 'appointment_date': local_dt_form.strftime('%Y-%m-%d'), 'appointment_time': local_dt_form.strftime('%H:%M'), 'services_text': appt.requested_services_text, 'notes': appt.notes, 'status': appt.status, 'groomer_id': appt.groomer_id, 'dog': appt.dog, 'groomer': appt.groomer}
    log_activity("Viewed Edit Appointment page", details=f"Appt ID: {appointment_id}")
    return render_template('edit_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=form_data, appointment_id=appointment_id)

@app.route('/appointment/<int:appointment_id>/delete', methods=['POST'])
@login_required
def delete_appointment(appointment_id):
    appt = Appointment.query.options(db.joinedload(Appointment.dog)).get_or_404(appointment_id)
    dog_name = appt.dog.name
    local_time = appt.appointment_datetime.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
    time_str = local_time.strftime('%Y-%m-%d %I:%M %p %Z')
    try:
        _sync_appointment_to_google_calendar(appt, event_type='delete')
        gcal_id_log = appt.google_event_id
        db.session.delete(appt); db.session.commit()
        log_activity("Deleted Local Appt", details=f"Appt ID: {appointment_id}, Dog: {dog_name}, GCal: {gcal_id_log}")
        flash(f"Appt for {dog_name} on {time_str} deleted!", "success")
    except Exception as e:
        db.session.rollback(); app.logger.error(f"Error deleting appt {appointment_id}: {e}", exc_info=True)
        flash("Error deleting appointment.", "danger")
    return redirect(url_for('calendar_view'))

# --- Google Calendar Integration Routes ---
@app.route('/google/authorize')
@admin_required
def google_authorize():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or "YOUR_GOOGLE_CLIENT_ID" in GOOGLE_CLIENT_ID:
        flash("Google Calendar integration not configured by admin.", "danger")
        app.logger.error("GCal OAuth: Client ID/Secret missing or placeholder.")
        return redirect(url_for('management'))
    session['oauth_state'] = str(uuid.uuid4())
    redirect_uri_to_use = os.environ.get("GOOGLE_REDIRECT_URI", url_for('google_callback', _external=True))
    client_config = {"web": {
        "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, 
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", 
        "token_uri": "https://oauth2.googleapis.com/token", 
        "redirect_uris": [redirect_uri_to_use]
    }}
    try:
        flow = Flow.from_client_config(client_config=client_config, scopes=GOOGLE_SCOPES, 
                                       state=session['oauth_state'], 
                                       redirect_uri=redirect_uri_to_use)
        auth_url, state = flow.authorization_url(access_type='offline', prompt='consent', include_granted_scopes='true')
        session['oauth_state'] = state 
        log_activity("Admin initiated Shared GCal auth")
        return redirect(auth_url)
    except Exception as e:
        app.logger.error(f"Error creating GCal OAuth flow: {e}", exc_info=True)
        flash("Could not initiate GCal authorization. Check server logs.", "danger"); return redirect(url_for('management'))

@app.route('/google/callback')
@admin_required
def google_callback():
    state_session = session.pop('oauth_state', None)
    state_google = request.args.get('state')
    if state_session is None or state_session != state_google:
        app.logger.error(f"OAuth state mismatch. Session: {state_session}, Google: {state_google}")
        flash('Invalid state from Google. Auth failed.', 'danger'); abort(400) 
    if 'error' in request.args:
        error_msg = request.args.get('error')
        app.logger.error(f"GCal OAuth error on callback: {error_msg}")
        flash(f"GCal authorization failed: {error_msg}", 'danger'); return redirect(url_for('management'))
    
    redirect_uri_to_use = os.environ.get("GOOGLE_REDIRECT_URI", url_for('google_callback', _external=True))
    actual_request_url = request.url
    if 'up.railway.app' in request.host_url and not actual_request_url.startswith('https'):
        actual_request_url = actual_request_url.replace('http://', 'https://', 1)

    client_config = {"web": {
        "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, 
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", 
        "token_uri": "https://oauth2.googleapis.com/token", 
        "redirect_uris": [redirect_uri_to_use]
    }}
    flow = Flow.from_client_config(client_config=client_config, scopes=GOOGLE_SCOPES, 
                                   state=state_google, redirect_uri=redirect_uri_to_use)
    try:
        flow.fetch_token(authorization_response=actual_request_url)
        credentials = flow.credentials
        token_file_path = app.config.get('SHARED_TOKEN_FILE')
        os.makedirs(os.path.dirname(token_file_path), exist_ok=True)
        with open(token_file_path, 'w') as token_file: 
            token_file.write(credentials.to_json())
        log_activity("Completed Shared GCal authorization")
        flash('Successfully connected to Shared Google Calendar!', 'success')
        app.logger.info(f"Stored Shared GCal credentials: {token_file_path}")
    except Exception as e:
        app.logger.error(f"Error during Shared GCal token fetch/store: {e}", exc_info=True)
        flash(f'Failed to store Shared GCal credentials: {str(e)}', 'danger')
    return redirect(url_for('management'))

# --- Legal Pages Routes (NEW) ---
@app.route('/user-agreement')
def view_user_agreement():
    return render_template('user_agreement.html')

@app.route('/privacy-policy')
def view_privacy_policy():
    return render_template('privacy_policy.html')

# --- Other Routes ---
@app.route('/logs')
@admin_required
def view_logs():
    log_activity("Viewed Activity Log page")
    page = request.args.get('page', 1, type=int); per_page = 50
    logs_pagination = ActivityLog.query.options(db.joinedload(ActivityLog.user)).order_by(ActivityLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('logs.html', logs_pagination=logs_pagination)

# --- Error Handlers ---
@app.errorhandler(403)
def forbidden_error(e):
    log_activity(f"403 Error - Forbidden: {request.path}", details=str(e))
    return render_template('errors/403.html'), 403

@app.errorhandler(404)
def page_not_found(e):
    log_activity(f"404 Error - Page Not Found: {request.path}", details=str(e))
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    db.session.rollback()
    app.logger.error(f"500 Internal Server Error: {e}", exc_info=True)
    log_activity(f"500 Error - Internal Server Error: {request.path}", details=str(e))
    return render_template('errors/500.html'), 500

# --- Initialization function for Railway ---
def initialize_app_on_startup(current_app):
    with current_app.app_context():
        current_app.logger.info("Application startup: Initializing persistent data directories and database...")
        
        db_file_path = current_app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        upload_folder_path = current_app.config.get('UPLOAD_FOLDER', '')
        shared_token_file_path = current_app.config.get('SHARED_TOKEN_FILE')

        if db_file_path: 
            db_dir = os.path.dirname(db_file_path)
            if db_dir and not os.path.exists(db_dir): 
                try:
                    os.makedirs(db_dir, exist_ok=True)
                    current_app.logger.info(f"Created database directory: {db_dir}")
                except Exception as e:
                    current_app.logger.error(f"Failed to create database directory {db_dir}: {e}")
        
        if upload_folder_path and not os.path.exists(upload_folder_path):
            try:
                os.makedirs(upload_folder_path, exist_ok=True)
                current_app.logger.info(f"Created upload folder: {upload_folder_path}")
            except Exception as e:
                current_app.logger.error(f"Failed to create upload folder {upload_folder_path}: {e}")

        if shared_token_file_path:
            token_dir = os.path.dirname(shared_token_file_path)
            if token_dir and not os.path.exists(token_dir):
                try:
                    os.makedirs(token_dir, exist_ok=True)
                    current_app.logger.info(f"Created token directory: {token_dir}")
                except Exception as e:
                    current_app.logger.error(f"Failed to create token directory {token_dir}: {e}")
        try:
            inspector = db.inspect(db.engine)
            if not inspector.has_table("user"): 
                current_app.logger.info("Database tables not found, creating them...")
                db.create_all()
                current_app.logger.info("Database tables created successfully.")
            else:
                current_app.logger.info("Database tables already exist.")
        except Exception as e:
            current_app.logger.error(f"Error during database table check/creation: {e}", exc_info=True)

if os.environ.get('RAILWAY_ENVIRONMENT') or not os.environ.get('WERKZEUG_RUN_MAIN'):
    initialize_app_on_startup(app)


# --- Main Execution Block (for local development) ---
if __name__ == '__main__':
    HOST = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    PORT = int(os.environ.get('FLASK_RUN_PORT', 5000))
    DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 't']
    LOCAL_APP_URL = f"http://127.0.0.1:{PORT}/"

    if PERSISTENT_DATA_ROOT == BASE_DIR: 
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            app.logger.info(f"Created local upload folder: {UPLOAD_FOLDER}")
        
        _token_file_for_local_dev = os.path.join(BASE_DIR, 'shared_google_token.json')
        if not os.path.exists(os.path.dirname(_token_file_for_local_dev)):
             os.makedirs(os.path.dirname(_token_file_for_local_dev), exist_ok=True)
             app.logger.info(f"Created local token directory: {os.path.dirname(_token_file_for_local_dev)}")


    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try: s.connect(('10.255.255.255', 1)); IP = s.getsockname()[0]
        except Exception: IP = '127.0.0.1'
        finally: s.close()
        return IP

    def open_browser_once():
        if not os.environ.get("WERKZEUG_RUN_MAIN"): 
            def _open():
                time.sleep(1.5)
                app.logger.info(f"Attempting to open app in browser: {LOCAL_APP_URL}")
                try: webbrowser.open_new_tab(LOCAL_APP_URL)
                except webbrowser.Error as e_wb: app.logger.warning(f"Failed to open browser: {e_wb}")
            threading.Thread(target=_open, daemon=True).start()

    with app.app_context():
        if not os.path.exists(DATABASE_PATH.replace(PERSISTENT_DATA_ROOT, BASE_DIR) if PERSISTENT_DATA_ROOT != BASE_DIR else DATABASE_PATH):
            app.logger.info(f"Local database not found at {DATABASE_PATH}, creating tables...")
            db.create_all()
        else:
            app.logger.info(f"Local database found at {DATABASE_PATH}")

        if check_initial_setup():
            app.logger.info(f"Initial admin setup required. Navigate to {LOCAL_APP_URL}initial_setup")


    local_ip_address = get_local_ip()
    app.logger.info(f"Starting Flask development server...")
    app.logger.info(f"Environment: {'development' if DEBUG_MODE else 'production'}")
    app.logger.info(f"Debug mode: {'on' if DEBUG_MODE else 'off'}")
    app.logger.info(f"Accessible on your computer at: {LOCAL_APP_URL}")
    if HOST == '0.0.0.0' and local_ip_address != '127.0.0.1':
        app.logger.info(f"Accessible on your local network at: http://{local_ip_address}:{PORT}/")
    
    if DEBUG_MODE: open_browser_once()
    app.run(host=HOST, port=PORT, debug=DEBUG_MODE, use_reloader=DEBUG_MODE)
