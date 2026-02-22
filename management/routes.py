from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app, session, abort, send_file, jsonify, send_from_directory, after_this_request
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from werkzeug.utils import secure_filename
import os
import imghdr
import sqlite3
import tempfile
import zipfile
import shutil
import werkzeug
import calendar
import uuid
from datetime import datetime, timedelta, timezone, time
from flask import (
    Blueprint, render_template, url_for, flash, redirect, request, 
    session, g, current_app, send_file, after_this_request
)
from sqlalchemy import text
from extensions import db
from sqlalchemy.exc import IntegrityError
from decimal import Decimal, InvalidOperation
from functools import wraps
import datetime
from models import User, Service, Appointment, ActivityLog, Store, Dog, Owner, AppointmentRequest
from utils import allowed_file, log_activity, service_names_from_ids
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import json
from google.oauth2.credentials import Credentials as GoogleCredentials
import pytz
import re
from dateutil import tz
from sqlalchemy import or_, func
from dateutil import parser as dateutil_parser
import shutil
from zipfile import ZipFile, ZIP_DEFLATED
import tempfile
from werkzeug.utils import secure_filename
from datetime import datetime
from notifications.email_utils import send_appointment_confirmation_email, send_appointment_cancelled_email, send_appointment_edited_email
from flask_wtf import FlaskForm
from wtforms import FileField
from wtforms.validators import DataRequired

# Form for database import
class DatabaseImportForm(FlaskForm):
    database_file = FileField('Database File (.db)', validators=[
        FileRequired(),
        FileAllowed(['db'], 'SQLite database files only!')
    ])

management_bp = Blueprint('management', __name__)

# --- Helpers ---
NOTIFICATION_SETTINGS_FILE = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'notification_settings.json')


# Decorator for admin routes
def admin_required(f):
    """
    Decorator to ensure that only admin users can access a route.
    Redirects non-admin users to the home page with a flash message.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, 'user') or g.user is None or not g.user.is_admin:
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def load_notification_preferences():
    """
    Loads notification preferences from notification_settings.json (in the main app directory).
    """
    notification_settings_path = os.path.join(current_app.root_path, 'notification_settings.json')
    try:
        with open(notification_settings_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        current_app.logger.error(f"Could not load notification settings: {e}")
        return {}

def save_notification_preferences(preferences):
    """
    Saves notification preferences to notification_settings.json (in the main app directory).
    """
    notification_settings_path = os.path.join(current_app.root_path, 'notification_settings.json')
    try:
        with open(notification_settings_path, 'w') as f:
            json.dump(preferences, f, indent=4)
        return True
    except Exception as e:
        current_app.logger.error(f"Could not save notification settings: {e}")
        return False

def _handle_user_picture_upload(user_instance, request_files):
    """
    Handles the upload of a user's profile picture.
    Generates a unique filename and deletes the old picture if a new one is uploaded.
    """
    if 'user_picture' not in request_files:
        return None
    file = request_files['user_picture']
    import imghdr
    from werkzeug.utils import secure_filename
    from utils import allowed_file
    if file and file.filename != '' and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        # Generate a unique, secure filename
        new_filename = secure_filename(f"user_{user_instance.id or 'temp'}_{uuid.uuid4().hex[:8]}.{ext}")
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], new_filename)
        os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)

        # Check MIME type using imghdr BEFORE saving
        file.stream.seek(0)
        header_bytes = file.read(512)
        file.stream.seek(0)
        detected_type = imghdr.what(None, h=header_bytes)
        if detected_type not in {'jpeg', 'png', 'gif', 'webp'}:
            flash("Uploaded file is not a valid image type.", "danger")
            current_app.logger.warning(f"Rejected user picture upload: invalid MIME type {detected_type}")
            return None

        # If there's an old picture, delete it to avoid orphaned files
        if user_instance.picture_filename and user_instance.picture_filename != new_filename:
            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], user_instance.picture_filename)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    current_app.logger.info(f"Deleted old user pic: {old_path}")
                except OSError as e_rem:
                    current_app.logger.error(f"Could not delete old user pic {old_path}: {e_rem}")
        try:
            file.save(file_path)
            current_app.logger.info(f"Saved new user pic: {file_path}")
            return new_filename
        except Exception as e_save:
            flash(f"Failed to save user picture: {e_save}", "warning")
            current_app.logger.error(f"Failed to save user pic {file_path}: {e_save}", exc_info=True)
    elif file and file.filename != '':
        flash("Invalid file type for user picture.", "warning")
        current_app.logger.warning(f"Rejected user picture upload: disallowed extension for file {file.filename}")
    return None

def get_date_range(range_type, start_date_str=None, end_date_str=None, store_timezone_str=None):
    """
    Calculates the start and end UTC datetimes for various report date ranges.
    """
    # NOTE: BUSINESS_TIMEZONE is currently set to timezone.utc.
    # If your application uses a specific business timezone, ensure it's properly configured
    # and used here for accurate date range calculations.
    if store_timezone_str:
        try:
            BUSINESS_TIMEZONE = pytz.timezone(store_timezone_str)
        except pytz.UnknownTimeZoneError:
            current_app.logger.warning(f"Unknown timezone: {store_timezone_str}, falling back to UTC")
            BUSINESS_TIMEZONE = pytz.UTC
    else:
        BUSINESS_TIMEZONE = pytz.UTC

    today_local = datetime.now(BUSINESS_TIMEZONE).date()
    start_local, end_local = None, None
    period_display = "Invalid Range"

    if range_type == 'today':
        start_local = BUSINESS_TIMEZONE.localize(datetime.combine(today_local, time.min))
        end_local = BUSINESS_TIMEZONE.localize(datetime.combine(today_local, time.max))
        period_display = f"Today, {start_local.strftime('%B %d, %Y')}"
    elif range_type == 'this_week':
        start_of_week_local_date = today_local - timedelta(days=today_local.weekday())
        end_of_week_local_date = start_of_week_local_date + timedelta(days=6)
        start_local = BUSINESS_TIMEZONE.localize(datetime.combine(start_of_week_local_date, time.min))
        end_local = BUSINESS_TIMEZONE.localize(datetime.combine(end_of_week_local_date, time.max))
        period_display = f"This Week: {start_local.strftime('%b %d')} - {end_local.strftime('%b %d, %Y')}"
    elif range_type == 'this_month':
        start_of_month_local_date = today_local.replace(day=1)
        _, num_days_in_month = calendar.monthrange(today_local.year, today_local.month)
        end_of_month_local_date = today_local.replace(day=num_days_in_month)
        start_local = BUSINESS_TIMEZONE.localize(datetime.combine(start_of_month_local_date, time.min))
        end_local = BUSINESS_TIMEZONE.localize(datetime.combine(end_of_month_local_date, time.max))
        period_display = f"This Month: {start_local.strftime('%B %Y')}"
    elif range_type == 'custom':
        try:
            if not start_date_str or not end_date_str:
                flash("Both start and end dates are required for a custom range.", "danger")
                return None, None, "Error: Incomplete Custom Dates"
            start_local_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_local_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if start_local_date > end_local_date:
                flash("Start date cannot be after end date.", "danger")
                return None, None, "Error: Invalid Custom Date Order"
            start_local = BUSINESS_TIMEZONE.localize(datetime.combine(start_local_date, time.min))
            end_local = BUSINESS_TIMEZONE.localize(datetime.combine(end_local_date, time.max))
            period_display = f"Custom: {start_local.strftime('%b %d, %Y')} - {end_local.strftime('%b %d, %Y')}"
        except ValueError:
            flash("Invalid custom date format. Please useYYYY-MM-DD.", "danger") 
            return None, None, "Error: Invalid Date Format"
    else:
        flash("Unknown date range type selected.", "danger")
        return None, None, "Error: Unknown Date Range"
    
    if start_local and end_local:
        start_utc = start_local.astimezone(pytz.UTC)
        end_utc = end_local.astimezone(pytz.UTC)
        return start_utc, end_utc, period_display
    return None, None, period_display

# --- Management Routes ---
@management_bp.route('/pending_appointments')
@admin_required
def pending_appointments():
    """Displays pending customer appointment requests for the current store."""
    store_id = session.get('store_id')
    pending_requests = AppointmentRequest.query.filter_by(store_id=store_id, status='pending').order_by(AppointmentRequest.created_at.asc()).all()
    store = Store.query.get(store_id) if store_id else None
    public_page_url = url_for('public.public_store_page', store_username=store.username, _external=True) if store else None
    return render_template('pending_appointments.html', requests=pending_requests, public_page_url=public_page_url)

@management_bp.route('/pending_appointments/<int:req_id>/approve', methods=['POST'])
@admin_required
def approve_appointment_request(req_id):
    """Approve an appointment request, converting it into Owner, Dog, and Appointment records."""
    req = AppointmentRequest.query.get_or_404(req_id)
    if req.status != 'pending':
        flash('Request already processed.', 'warning')
        return redirect(url_for('management.pending_appointments'))
    try:
        # Create owner if phone or email not already
        # Use linked owner if provided
        owner = None
        if req.owner_id:
            owner = Owner.query.get(req.owner_id)
        if not owner:
            owner = Owner.query.filter_by(phone_number=req.phone, store_id=req.store_id).first()
        if not owner:
            owner = Owner(name=req.customer_name, phone_number=req.phone, email=req.email, store_id=req.store_id, created_by_user_id=g.user.id)
            db.session.add(owner)
            db.session.flush()
        # Create dog
        if req.dog_id:
            dog = Dog.query.get(req.dog_id)
        else:
            dog = Dog(name=(req.dog_name or 'Dog'), owner_id=owner.id, store_id=req.store_id, created_by_user_id=g.user.id)
            db.session.add(dog)
            db.session.flush()
        # Create appointment with placeholder datetime parse
        preferred_dt = datetime.strptime(req.preferred_datetime, '%Y-%m-%d %H:%M') if req.preferred_datetime else datetime.utcnow()
        appt = Appointment(
            dog_id=dog.id,
            appointment_datetime=preferred_dt,
            notes=req.notes,
            status='Scheduled',
            created_by_user_id=g.user.id,
            store_id=req.store_id,
            requested_services_text=req.requested_services_text,
            groomer_id=req.groomer_id
        )
        db.session.add(appt)
        db.session.flush()  # Flush to get the appt ID
        
        # Commit the transaction first
        req.status = 'approved'
        db.session.commit()
        
        # Get store info for email and calendar
        store = Store.query.get(req.store_id)
        groomer = User.query.get(req.groomer_id) if req.groomer_id else None
        
        # Ensure we have a valid store
        if not store:
            current_app.logger.error(f"No store found for store_id: {req.store_id}")
            flash('Error: Store information not found.', 'danger')
            return redirect(url_for('management.pending_appointments'))
        
        # Send confirmation email
        try:
            if owner.email:
                send_appointment_confirmation_email(
                    store=store,
                    owner=owner,
                    dog=dog,
                    appointment=appt,
                    groomer=groomer,
                    services_text=req.requested_services_text
                )
                current_app.logger.info(f"Confirmation email sent for appointment {appt.id} to {owner.email}")
        except Exception as email_error:
            current_app.logger.error(f"Error sending confirmation email for appointment {appt.id}: {email_error}", exc_info=True)
            # Continue even if email fails
        
        # Sync with Google Calendar if enabled
        if store and store.google_token_json:
            try:
                # Use the improved get_google_credentials function
                from appointments.google_calendar_sync import get_google_credentials
                
                credentials = get_google_credentials(store)
                if not credentials:
                    raise Exception("Failed to obtain valid Google credentials")
                    
                service = build('calendar', 'v3', credentials=credentials)
                # Make sure we have a calendar ID
                calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'
                
                # Format the event
                event = {
                    'summary': f"[SCHEDULED] ({dog.name}) Appointment",
                    'description': f"Owner: {owner.name}\nPhone: {owner.phone_number}\nGroomer: {groomer.username if groomer else 'Not assigned'}\nServices: {service_names_from_ids(req.requested_services_text) if req.requested_services_text else 'Not specified'}\nNotes: {req.notes or 'No notes'}\nStatus: Scheduled",
                    'start': {
                        'dateTime': appt.appointment_datetime.isoformat(),
                        'timeZone': store.timezone if store and store.timezone else 'America/New_York',
                    },
                    'end': {
                        'dateTime': (appt.appointment_datetime + timedelta(hours=1)).isoformat(),
                        'timeZone': store.timezone if store and store.timezone else 'America/New_York',
                    },
                    'reminders': {
                        'useDefault': True,
                    },
                }
                
                # Add the event to Google Calendar
                created_event = service.events().insert(
                    calendarId=calendar_id,
                    body=event
                ).execute()
                current_app.logger.info(f"[GCAL SYNC] Successfully created new Google event for appointment {appt.id}")
                appt.google_event_id = created_event.get('id')
                db.session.commit()
                flash('Appointment synced to Google Calendar.', 'success')
            except Exception as calendar_error:
                current_app.logger.error(f"Error syncing with Google Calendar for appointment {appt.id}: {calendar_error}")
                flash('Appointment approved, but failed to sync with Google Calendar.', 'warning')
        
        flash('Appointment request approved and scheduled. Confirmation email sent.', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error approving request {req_id}: {e}", exc_info=True)
        flash('Error approving request.', 'danger')
    return redirect(url_for('management.pending_appointments'))

@management_bp.route('/pending_appointments/<int:req_id>/edit', methods=['GET','POST'])
@admin_required
def edit_appointment_request(req_id):
    req = AppointmentRequest.query.get_or_404(req_id)
    if req.status != 'pending':
        flash('Only pending requests can be edited.', 'warning')
        return redirect(url_for('management.pending_appointments'))
    if request.method == 'POST':
        req.customer_name = request.form.get('customer_name','').strip()
        req.phone = request.form.get('phone','').strip()
        req.email = request.form.get('email','').strip()
        req.dog_name = request.form.get('dog_name','').strip()
        date = request.form.get('preferred_date','').strip()
        time = request.form.get('preferred_time','').strip()
        req.preferred_datetime = f"{date} {time}".strip() if date and time else ''
        req.notes = request.form.get('notes','').strip()
        # Services (list of IDs)
        services_selected = request.form.getlist('services')
        req.requested_services_text = ','.join(services_selected) if services_selected else None
        # Groomer assignment
        groomer_val = request.form.get('groomer_id')
        req.groomer_id = int(groomer_val) if groomer_val else None
        # Link to existing owner/dog if chosen
        owner_id_val = request.form.get('owner_id')
        req.owner_id = int(owner_id_val) if owner_id_val else None
        dog_id_val = request.form.get('dog_id')
        req.dog_id = int(dog_id_val) if dog_id_val else None
        db.session.commit()
        flash('Request updated.', 'success')
        return redirect(url_for('management.pending_appointments'))
    # GET render form
    public_page_url = url_for('public.public_store_page', store_username=req.store.username, _external=True)
    # split preferred_datetime
    pref_date, pref_time = '', ''
    if req.preferred_datetime and ' ' in req.preferred_datetime:
        pref_date, pref_time = req.preferred_datetime.split(' ',1)
    from sqlalchemy.orm import joinedload
    owners = Owner.query.options(joinedload(Owner.dogs)).filter_by(store_id=req.store_id).all()
    # Fetch services and groomers lists for dropdowns
    services = Service.query.filter_by(store_id=req.store_id, item_type='service').order_by(Service.name.asc()).all()
    from sqlalchemy import or_
    groomers = User.query.filter(
        User.store_id == req.store_id,
        or_(User.role == 'groomer', User.role == 'admin')
    ).order_by(User.username.asc()).all()

    owners_data = [{
        'id': o.id,
        'name': o.name,
        'phone': o.phone_number,
        'dogs': [{'id': d.id, 'name': d.name} for d in o.dogs]
    } for o in owners]
    return render_template('edit_appointment_request.html', req=req, public_page_url=public_page_url, pref_date=pref_date, pref_time=pref_time,
                           owners=owners, owners_json=owners_data, services=services, groomers=groomers)

@management_bp.route('/pending_appointments/<int:req_id>/reject', methods=['POST'])
@admin_required
def reject_appointment_request(req_id):
    req = AppointmentRequest.query.get_or_404(req_id)
    if req.status != 'pending':
        flash('Request already processed.', 'warning')
    else:
        req.status = 'rejected'
        db.session.commit()
        flash('Appointment request rejected.', 'info')
    return redirect(url_for('management.pending_appointments'))

@management_bp.route('/management')
@admin_required
def management():
    """
    Displays the main management dashboard.
    Checks Google Calendar/Gmail connection status for the current store.
    """
    log_activity("Viewed Management page")
    store = None
    is_google_calendar_connected = False
    is_gmail_for_sending_connected = False
    
    if hasattr(g, 'user') and g.user and g.user.store_id:
        # Filter store by the current user's store_id
        store = Store.query.filter_by(id=g.user.store_id).first()
        if store and store.google_token_json:
            try:
                token_data = json.loads(store.google_token_json)
                # Handle both 'scopes' (list) and 'scope' (space-separated string)
                if 'scopes' in token_data:
                    scopes = [s.strip().rstrip(';') for s in token_data['scopes']]
                elif 'scope' in token_data:
                    scopes = token_data['scope'].split()
                else:
                    scopes = []
                current_app.logger.info(f"[DEBUG] store.google_token_json: {store.google_token_json}")
                current_app.logger.info(f"[DEBUG] parsed scopes: {scopes}")
                is_google_calendar_connected = 'https://www.googleapis.com/auth/calendar' in scopes
                is_gmail_for_sending_connected = 'https://www.googleapis.com/auth/gmail.send' in scopes
            except Exception as e:
                current_app.logger.error(f"[DEBUG] Error parsing google_token_json: {e}")
                
    public_page_url = None
    if store:
        public_page_url = url_for('public.public_store_page', store_username=store.username, _external=True)
    return render_template('management.html',
        public_page_url=public_page_url,
        is_google_calendar_connected=is_google_calendar_connected,
        is_gmail_for_sending_connected=is_gmail_for_sending_connected)

@management_bp.route('/manage/users')
@admin_required
def manage_users():
    """
    Displays a list of users for the current store.
    """
    log_activity("Viewed User Management page")
    # Filter users by the current store's ID
    users = User.query.filter_by(store_id=session.get('store_id')).order_by(User.username).all()
    return render_template('manage_users.html', users=users)

@management_bp.route('/manage/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    """
    Handles adding a new user to the current store.
    Ensures the new user is associated with the current store's ID.
    """
    store_id = session.get('store_id')  # Get store_id from session
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        email = request.form.get('email', '').strip()
        security_question = request.form.get('security_question', '')
        security_answer = request.form.get('security_answer', '')
        is_admin = 'is_admin' in request.form
        is_groomer = 'is_groomer' in request.form 
        
        errors = {}
        if not username: errors['username'] = "Username required."
        if not password: errors['password'] = "Password required."
        if password != confirm_password: errors['password_confirm'] = "Passwords do not match."
        if len(password) < 8 and password: errors['password_length'] = "Password too short."
        if not security_question: errors['security_question'] = "Security question required."
        if not security_answer: errors['security_answer'] = "Security answer required."
        
        # Check for username conflict only within the current store
        if User.query.filter_by(username=username, store_id=store_id).first():
            errors['username_conflict'] = "Username already exists in this store."
        
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict()
            form_data['is_admin'] = is_admin
            form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='add', user_data=form_data), 400
        
        new_user = User(username=username, is_admin=is_admin, is_groomer=is_groomer, store_id=store_id, security_question=security_question, email=email)  # Assign store_id and email
        new_user.set_password(password)
        new_user.set_security_answer(security_answer)
        
        try:
            db.session.add(new_user)
            db.session.flush() # Flush to get new_user.id for picture upload filename
            
            uploaded_filename = _handle_user_picture_upload(new_user, request.files)
            if uploaded_filename:
                new_user.picture_filename = uploaded_filename
            
            db.session.commit()
            log_activity("Added User", details=f"Username: {username}, Admin: {is_admin}, Groomer: {is_groomer}, Store ID: {store_id}")
            flash(f"User '{username}' added.", "success")
            return redirect(url_for('management.manage_users'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding user: {e}", exc_info=True)
            flash("Error adding user.", "danger")
            form_data = request.form.to_dict()
            form_data['is_admin'] = is_admin
            form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='add', user_data=form_data), 500
    
    log_activity("Viewed Add User page")
    return render_template('user_form.html', mode='add', user_data={'is_groomer': True}) 

@management_bp.route('/manage/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    """
    Handles editing an existing user's profile.
    Ensures that only users from the current store can be edited.
    Prevents removing admin status from the last admin in the store.
    """
    store_id = session.get('store_id')  # Get store_id from session
    
    # Fetch user to edit, ensuring they belong to the current store
    user_to_edit = User.query.filter_by(id=user_id, store_id=store_id).first_or_404()
    
    if request.method == 'POST':
        original_username = user_to_edit.username
        new_username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        email = request.form.get('email', '').strip()
        security_question = request.form.get('security_question', '')
        security_answer = request.form.get('security_answer', '')
        is_admin = 'is_admin' in request.form
        is_groomer = 'is_groomer' in request.form
        
        errors = {}
        if not new_username: errors['username'] = "Username required."
        
        # Check for username conflict only within the current store, excluding the user being edited
        if new_username != original_username and User.query.filter(User.id != user_id, User.username == new_username, User.store_id==store_id).first():
            errors['username_conflict'] = "Username already taken in this store."
        
        password_changed = False
        if password:
            if password != confirm_password: errors['password_confirm'] = "Passwords do not match."
            if len(password) < 8: errors['password_length'] = "Password too short (min 8 chars)."
            else: password_changed = True
        
        # Prevent removing admin status from the last admin in the current store
        if user_to_edit.is_admin and not is_admin: 
            admin_count = User.query.filter_by(is_admin=True, store_id=store_id).count()
            if admin_count <= 1: 
                errors['last_admin'] = "Cannot remove admin status from the last administrator in this store."
                is_admin = True # Force is_admin back to True if it's the last admin
        
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict()
            form_data['id'] = user_id
            form_data['picture_filename'] = user_to_edit.picture_filename # Keep existing picture filename
            form_data['is_admin'] = is_admin
            form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='edit', user_data=form_data), 400
        
        user_to_edit.username = new_username
        user_to_edit.email = email
        if password_changed: user_to_edit.set_password(password)
        user_to_edit.is_admin = is_admin
        user_to_edit.is_groomer = is_groomer
        
        # Update security question if provided
        if security_question:
            user_to_edit.security_question = security_question
            
        # Update security answer if provided
        if security_answer:
            user_to_edit.set_security_answer(security_answer)
        
        try:
            uploaded_filename = _handle_user_picture_upload(user_to_edit, request.files)
            if uploaded_filename:
                user_to_edit.picture_filename = uploaded_filename
            
            db.session.commit()
            log_activity("Edited User", details=f"User ID: {user_id}, Username: {new_username}, Admin: {is_admin}, Groomer: {is_groomer}, Store ID: {store_id}")
            flash(f"User '{new_username}' updated.", "success")
            return redirect(url_for('management.manage_users'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating user {user_id}: {e}", exc_info=True)
            flash("Error updating user.", "danger")
            form_data = request.form.to_dict()
            form_data['id'] = user_id
            form_data['picture_filename'] = user_to_edit.picture_filename
            form_data['is_admin'] = is_admin
            form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='edit', user_data=form_data), 500
    
    log_activity("Viewed Edit User page", details=f"User ID: {user_id}")
    return render_template('user_form.html', mode='edit', user_data=user_to_edit) 

@management_bp.route('/manage/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    """
    Handles deleting a user.
    Ensures that only users from the current store can be deleted.
    Prevents deleting own account or the last admin in the store.
    """
    store_id = session.get('store_id')  # Get store_id from session
    
    # Fetch user to delete, ensuring they belong to the current store
    user_to_delete = User.query.filter_by(id=user_id, store_id=store_id).first_or_404()
    
    if user_to_delete.id == g.user.id:
        flash("Cannot delete your own account.", "danger")
        return redirect(url_for('management.manage_users'))
    
    # Prevent deleting the last admin in the current store
    if user_to_delete.is_admin and User.query.filter_by(is_admin=True, store_id=store_id).count() <= 1:
        flash("Cannot delete the last administrator in this store.", "danger")
        return redirect(url_for('management.manage_users'))
    
    username_deleted = user_to_delete.username
    pic_to_delete = user_to_delete.picture_filename
    
    try:
        # Set groomer_id to None for appointments associated with this user in the current store
        Appointment.query.filter_by(groomer_id=user_id, store_id=store_id).update({'groomer_id': None})
        
        db.session.delete(user_to_delete)
        db.session.commit()
        
        # Delete associated picture file if it exists
        if pic_to_delete:
            path = os.path.join(current_app.config['UPLOAD_FOLDER'], pic_to_delete)
            if os.path.exists(path):
                try:
                    os.remove(path)
                    current_app.logger.info(f"Deleted user pic: {path}")
                except OSError as e_rem:
                    current_app.logger.error(f"Could not delete user pic file {path}: {e_rem}")
        
        log_activity("Deleted User", details=f"Username: {username_deleted}, Store ID: {store_id}")
        flash(f"User '{username_deleted}' deleted.", "success")
    except IntegrityError as ie:
        db.session.rollback()
        current_app.logger.error(f"IntegrityError deleting user '{username_deleted}': {ie}", exc_info=True)
        flash(f"Could not delete '{username_deleted}'. Associated records might exist.", "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting user '{username_deleted}': {e}", exc_info=True)
        flash(f"Error deleting '{username_deleted}'.", "danger")
    
    return redirect(url_for('management.manage_users'))

@management_bp.route('/manage/services')
@admin_required
def manage_services():
    """
    Displays a list of services and fees for the current store.
    """
    store_id = session.get('store_id')  # Get store_id from session
    log_activity("Viewed Service/Fee Management page")
    # Filter services by the current store's ID
    all_items = Service.query.filter_by(store_id=store_id).order_by(Service.item_type, Service.name).all()
    services = [item for item in all_items if item.item_type == 'service']
    fees = [item for item in all_items if item.item_type == 'fee']
    store = Store.query.get(store_id)
    tax_enabled = getattr(store, 'tax_enabled', True)
    return render_template('manage_services.html', services=services, fees=fees, tax_enabled=tax_enabled)

@management_bp.route('/manage/toggle_taxes', methods=['POST'])
@admin_required
def toggle_taxes():
    store_id = session.get('store_id')
    store = Store.query.get(store_id)
    if not store:
        flash('Store not found.', 'danger')
        return redirect(url_for('management.manage_services'))
    tax_enabled = 'tax_enabled' in request.form
    store.tax_enabled = tax_enabled
    db.session.commit()
    flash(f'Taxes have been {"enabled" if tax_enabled else "disabled"} for all invoices and receipts.', 'success')
    return redirect(url_for('management.manage_services'))

@management_bp.route('/manage/services/add', methods=['GET', 'POST'])
@admin_required
def add_service():
    """
    Handles adding a new service or fee to the current store.
    Ensures the new item is associated with the current store's ID.
    """
    store_id = session.get('store_id')  # Get store_id from session
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
        
        # Check for duplicate service name only within the current store
        if Service.query.filter_by(name=name, store_id=store_id).first():
            errors['name_conflict'] = f"An item named '{name}' already exists in this store."
        
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            return render_template('service_form.html', mode='add', item_data=request.form.to_dict()), 400
        
        new_item = Service(name=name, description=description or None, base_price=float(price), item_type=item_type, created_by_user_id=g.user.id, store_id=store_id)  # Assign store_id
        
        try:
            db.session.add(new_item)
            db.session.commit()
            log_activity(f"Added {item_type.capitalize()}", details=f"Name: {name}, Price: {price:.2f}, Store ID: {store_id}")
            flash(f"{item_type.capitalize()} '{name}' added.", "success")
            return redirect(url_for('management.manage_services'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding {item_type}: {e}", exc_info=True)
            flash(f"Error adding {item_type}.", "danger")
            return render_template('service_form.html', mode='add', item_data=request.form.to_dict()), 500
    
    log_activity("Viewed Add Service/Fee page")
    return render_template('service_form.html', mode='add', item_data={})

@management_bp.route('/manage/services/<int:service_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_service(service_id):
    """
    Handles editing an existing service or fee.
    Ensures that only items from the current store can be edited.
    """
    store_id = session.get('store_id')  # Get store_id from session
    
    # Fetch item to edit, ensuring it belongs to the current store
    item_to_edit = Service.query.filter_by(id=service_id, store_id=store_id).first_or_404()
    
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
        except InvalidOperation:
            errors['base_price_invalid'] = "Invalid price format."
        
        # Check for duplicate name only within the current store, excluding the item being edited
        if name != original_name and Service.query.filter(Service.id != service_id, Service.name == name, Service.store_id==store_id).first():
            errors['name_conflict'] = f"Another item named '{name}' already exists in this store."
        
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict()
            form_data['id'] = service_id
            return render_template('service_form.html', mode='edit', item_data=form_data), 400
        
        item_to_edit.name = name
        item_to_edit.description = description or None
        item_to_edit.base_price = float(price)
        item_to_edit.item_type = item_type
        
        try:
            db.session.commit()
            log_activity(f"Edited {item_type.capitalize()}", details=f"ID: {service_id}, Name: {name}, Store ID: {store_id}")
            flash(f"{item_type.capitalize()} '{name}' updated.", "success")
            return redirect(url_for('management.manage_services'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing item {service_id}: {e}", exc_info=True)
            flash(f"Error updating {item_type}.", "danger")
            form_data = request.form.to_dict()
            form_data['id'] = service_id
            return render_template('service_form.html', mode='edit', item_data=form_data), 500
    
    log_activity(f"Viewed Edit {item_to_edit.item_type.capitalize()} page", details=f"ID: {service_id}")
    return render_template('service_form.html', mode='edit', item_data=item_to_edit)

@management_bp.route('/manage/services/<int:service_id>/delete', methods=['POST'])
@admin_required
def delete_service(service_id):
    """
    Handles deleting a service or fee.
    Ensures that only items from the current store can be deleted.
    """
    store_id = session.get('store_id')  # Get store_id from session
    
    # Fetch item to delete, ensuring it belongs to the current store
    item_to_delete = Service.query.filter_by(id=service_id, store_id=store_id).first_or_404()
    
    item_name = item_to_delete.name
    item_type = item_to_delete.item_type
    
    try:
        db.session.delete(item_to_delete)
        db.session.commit()
        log_activity(f"Deleted {item_type.capitalize()}", details=f"ID: {service_id}, Name: {item_name}, Store ID: {store_id}")
        flash(f"{item_type.capitalize()} '{item_name}' deleted.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting {item_type} '{item_name}': {e}", exc_info=True)
        flash(f"Error deleting '{item_name}'. It might be in use.", "danger")
    
    return redirect(url_for('management.manage_services'))

@management_bp.route('/manage/reports', methods=['GET', 'POST'])
@admin_required
def view_sales_reports():
    """
    Generates and displays sales reports based on selected criteria.
    Filters all data by the current store's ID.
    """
    store_id = session.get('store_id')  # Get store_id from session
    store = Store.query.get(store_id) if store_id else None

    # Filter groomers for the dropdown by the current store's ID
    all_groomers_for_dropdown = User.query.filter_by(store_id=store_id, is_groomer=True).order_by(User.username).all()
    
    report_data_processed = None
    report_period_display = "Report Not Yet Generated"
    selected_groomer_name_display = "All Groomers"

    if request.method == 'POST':
        log_activity("Sales Report Generation Attempt")
        date_range_type = request.form.get('date_range_type', 'today')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        groomer_id_str = request.form.get('groomer_id')

        store_timezone = store.timezone if store and store.timezone else 'UTC'
        start_utc, end_utc, report_period_display = get_date_range(date_range_type, start_date_str, end_date_str, store_timezone)

        if not start_utc or not end_utc:
            return render_template('reports_form.html', all_groomers=all_groomers_for_dropdown, report_period_display=report_period_display)

        # Filter appointments by store_id, status, and date range
        query = Appointment.query.filter(
            Appointment.store_id == store_id,  # ADDED STORE FILTER
            Appointment.status == 'Completed',
            Appointment.appointment_datetime >= start_utc,
            Appointment.appointment_datetime <= end_utc
        ).options(db.joinedload(Appointment.groomer))

        if groomer_id_str:
            try:
                selected_groomer_id = int(groomer_id_str)
                # Ensure the selected groomer belongs to the current store
                selected_groomer_user = User.query.filter_by(id=selected_groomer_id, store_id=store_id).first()
                if selected_groomer_user:
                    query = query.filter(Appointment.groomer_id == selected_groomer_id)
                    selected_groomer_name_display = selected_groomer_user.username
                else:
                    flash("Invalid Groomer selected for this store.", "warning")
                    selected_groomer_name_display = "Unknown Groomer (Invalid Selection)"
                    # Optionally, you might want to return early or adjust the query to not filter by groomer_id
                    # if an invalid groomer_id for the store was provided. For now, it will just not find them.
            except ValueError:
                flash("Invalid Groomer ID format.", "warning")

        completed_appointments_in_range = query.all()
        
        groomer_specific_reports = {}
        store_wide_summary = {'items_sold': {}, 'grand_total': Decimal('0.0')}
        
        # Filter services by the current store's ID
        all_services_from_db = Service.query.filter_by(store_id=store_id).all()
        service_prices_map = {s.name: Decimal(str(s.base_price)) for s in all_services_from_db}

        for appt in completed_appointments_in_range:
            appointment_actual_total = Decimal('0.0')
            if appt.checkout_total_amount is not None:
                try:
                    appointment_actual_total = Decimal(str(appt.checkout_total_amount))
                except InvalidOperation:
                    current_app.logger.warning(f"Invalid checkout_total_amount for Appt {appt.id}")
            
            # If checkout_total_amount is null or zero, recalculate based on services
            if appt.checkout_total_amount is None or appointment_actual_total == Decimal('0.0'):
                recalculated_total = Decimal('0.0')
                if appt.requested_services_text:
                    for service_name in [s.strip() for s in appt.requested_services_text.split(',') if s.strip()]:
                        recalculated_total += service_prices_map.get(service_name, Decimal('0.0'))
                appointment_actual_total = recalculated_total
                if appt.checkout_total_amount is None:
                     current_app.logger.info(f"Appt {appt.id}: checkout_total_amount was null. Used recalculated ${appointment_actual_total:.2f}")

            current_groomer_id = appt.groomer_id if appt.groomer_id else 0
            current_groomer_name = appt.groomer.username if appt.groomer else "Unassigned"

            if current_groomer_id not in groomer_specific_reports:
                groomer_specific_reports[current_groomer_id] = {
                    'groomer_name': current_groomer_name, 
                    'items_sold': {}, 
                    'total_groomer_sales': Decimal('0.0')
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
        log_activity("Sales Report Generated", details=f"Period: {report_period_display}, Groomer: {selected_groomer_name_display}, Store ID: {store_id}")
        return render_template('report_display.html', report_data=report_data_processed,
                               report_period_display=report_period_display,
                               selected_groomer_name=selected_groomer_name_display, all_groomers=all_groomers_for_dropdown)
    log_activity("Viewed Sales Report Form")
    return render_template('reports_form.html', all_groomers=all_groomers_for_dropdown, report_period_display=report_period_display)

@management_bp.route('/manage/notifications', methods=['GET', 'POST'])
@admin_required
def manage_notifications():
    """
    Manages notification settings.
    NOTE: Current implementation uses a global NOTIFICATION_PREFERENCES.
    For multi-store separation, these preferences should be stored per store in the database.
    """
    # Load from file instead of config
    NOTIFICATION_PREFERENCES = load_notification_preferences()

    if request.method == 'POST':
        NOTIFICATION_PREFERENCES['send_confirmation_email'] = 'send_confirmation_email' in request.form
        NOTIFICATION_PREFERENCES['send_reminder_email'] = 'send_reminder_email' in request.form
        reminder_days_str = request.form.getlist('reminder_days_before')
        try:
            NOTIFICATION_PREFERENCES['reminder_days_before'] = sorted([int(d) for d in reminder_days_str if d.isdigit()])
        except ValueError:
            flash("Invalid input for reminder days.", "danger")
        NOTIFICATION_PREFERENCES['default_reminder_time'] = request.form.get('default_reminder_time', '09:00')
        NOTIFICATION_PREFERENCES['sender_name'] = request.form.get('sender_name', 'Pawfection Grooming').strip()
        save_notification_preferences(NOTIFICATION_PREFERENCES)
        log_activity("Updated Notification Settings", details=str(NOTIFICATION_PREFERENCES))
        flash("Notification settings updated successfully!", "success")
        return redirect(url_for('management.manage_notifications'))

    log_activity("Viewed Manage Customer Notifications page")
    return render_template('manage_notifications.html', current_settings=NOTIFICATION_PREFERENCES)

@management_bp.route('/logs')
@admin_required
def view_logs():
    """
    Displays activity logs, filtered by the current store's ID.
    """
    store_id = session.get('store_id')  # Get store_id from session
    log_activity("Viewed Activity Log page")
    page = request.args.get('page', 1, type=int)
    per_page = 50
    # Filter activity logs by the current store's ID, joining with User to get store_id
    logs_pagination = ActivityLog.query.options(db.joinedload(ActivityLog.user)).join(User).filter(
        User.store_id == store_id
    ).order_by(ActivityLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('logs.html', logs_pagination=logs_pagination)

@management_bp.route('/google/authorize')
@admin_required
def google_authorize():
    """
    Initiates the Google OAuth authorization flow for the current store.
    """
    # Only allow admin users (already handled by @admin_required)
    if not g.user or not g.user.is_admin:
        flash("Only administrators can connect Google services.", "danger")
        return redirect(url_for('management.management'))

    # Clear old Google token to avoid scope mismatch errors for the current store
    if hasattr(g, 'user') and g.user and g.user.store_id:
        store = Store.query.filter_by(id=g.user.store_id).first() # Ensure we get the store for the current user
        if store:
            store.google_token_json = None
            db.session.commit()

    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI')
    if not client_id or not client_secret or not redirect_uri:
        flash("Google OAuth environment variables (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI) are not set.", "danger")
        return redirect(url_for('management.management'))

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": [redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ]
    )
    flow.redirect_uri = redirect_uri
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent' # Ensure refresh token is granted
    )
    session['google_oauth_state'] = state
    return redirect(authorization_url)

@management_bp.route('/google/oauth2callback')
@admin_required
def google_oauth2callback():
    """
    Handles the callback from Google OAuth after authorization.
    Saves the Google token to the current store's record in the database.
    """
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI')
    if not client_id or not client_secret or not redirect_uri:
        flash("Google OAuth environment variables are not set.", "danger")
        return redirect(url_for('management.management'))

    state = session.get('google_oauth_state')
    if not state or state != request.args.get('state'): # Validate state to prevent CSRF
        flash("OAuth state mismatch. Please try again.", "danger")
        return redirect(url_for('management.management'))

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": [redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ],
        state=state
    )
    flow.redirect_uri = redirect_uri
    authorization_response = request.url
    try:
        flow.fetch_token(authorization_response=authorization_response)
    except Exception as e:
        current_app.logger.error(f"Google OAuth error: {e}", exc_info=True)
        flash("Failed to authorize with Google. Please try again.", "danger")
        return redirect(url_for('management.management'))

    current_app.logger.info(f"[Google OAuth] Starting oauth2callback for user: {getattr(g.user, 'id', None)} store: {getattr(g.user, 'store_id', None)}")
    credentials = flow.credentials
    token_data = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token, # Important for long-lived access
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    current_app.logger.info(f"[Google OAuth] Token data to save: {token_data}")
    
    # Save token to the current store
    if hasattr(g, 'user') and g.user and g.user.store_id:
        store = Store.query.filter_by(id=g.user.store_id).first() # Ensure we get the store for the current user
        current_app.logger.info(f"[Google OAuth] Store loaded: {store}")
        if store:
            store.google_token_json = json.dumps(token_data)
            try:
                db.session.commit()
                current_app.logger.info(f"[Google OAuth] Token committed to DB for store {store.id}")
                
                # --- Test the token by making a Calendar API call ---
                # This ensures the token is valid and has the necessary permissions
                test_credentials = GoogleCredentials(
                    token=token_data.get('token') or token_data.get('access_token'),
                    refresh_token=token_data.get('refresh_token'),
                    token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                    client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
                    client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
                    scopes=token_data['scopes']
                )
                current_app.logger.info(f"[Google OAuth] Built test credentials. About to call Calendar API...")
                service = build('calendar', 'v3', credentials=test_credentials)
                try:
                    result = service.calendarList().list(maxResults=1).execute()
                    current_app.logger.info(f"[Google OAuth] Calendar API test succeeded for store {store.id}. Result: {result}")
                    log_activity("Connected Google Account for Calendar/Gmail")
                    flash("Google account connected successfully!", "success")
                except Exception as e:
                    # If test fails, clear the token to prevent partial connections
                    store.google_token_json = None
                    db.session.commit()
                    import traceback
                    tb = traceback.format_exc()
                    current_app.logger.error(f"[Google OAuth] Google token test failed: {e}\nTraceback:\\n{tb}")
                    flash("Failed to verify Google account connection. Please try again.", "danger")
            except Exception as e:
                db.session.rollback()
                import traceback
                tb = traceback.format_exc()
                current_app.logger.error(f"[Google OAuth] Failed to save Google token to store: {e}\nTraceback:\\n{tb}")
                flash("Failed to save Google token.", "danger")
        else:
            current_app.logger.error(f"[Google OAuth] Store not found for user {getattr(g.user, 'id', None)}")
            flash("Store not found. Cannot save Google token.", "danger")
    else:
        current_app.logger.error(f"[Google OAuth] No store context for user {getattr(g.user, 'id', None)}")
        flash("No store context. Cannot save Google token.", "danger")
    current_app.logger.info(f"[Google OAuth] oauth2callback complete for user: {getattr(g.user, 'id', None)} store: {getattr(g.user, 'store_id', None)}")
    return redirect(url_for('management.management'))

@management_bp.route('/manage/store/edit', methods=['GET', 'POST'])
@admin_required
def edit_store():
    """
    Allows admin to edit store information, including name, address, contact info, and timezone.
    """
    store = Store.query.filter_by(id=g.user.store_id).first()
    if not store:
        abort(404)

    # List of common timezones (can be expanded)
    timezones = pytz.all_timezones

    import re
    import shutil
    from werkzeug.utils import secure_filename
    
    if request.method == 'POST':
        errors = []
        # Username uniqueness check
        new_username = request.form.get('username', store.username)
        if new_username != store.username:
            existing = Store.query.filter_by(username=new_username).first()
            if existing and existing.id != store.id:
                errors.append('Username already exists. Please choose a different one.')
        # Email format validation
        email = request.form.get('email', store.email)
        if email and not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            errors.append('Invalid email format.')
        # Handle logo upload - Simplified and direct approach
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename and logo_file.filename != '':
            if not allowed_file(logo_file.filename):
                flash('Invalid file type. Only PNG, JPG, JPEG, GIF, and WEBP allowed.', 'danger')
            else:
                try:
                    # Validate MIME type content
                    logo_file.stream.seek(0)
                    header_bytes = logo_file.read(512)
                    logo_file.stream.seek(0)
                    detected_type = imghdr.what(None, h=header_bytes)
                    if detected_type not in {'jpeg', 'png', 'gif', 'webp'}:
                        flash('Invalid image content.', 'danger')
                    else:
                        # Get a clean filename
                        filename = secure_filename(logo_file.filename)

                        # Ensure directory exists
                        upload_folder = os.path.join(current_app.static_folder, 'uploads', 'store_logos')
                        os.makedirs(upload_folder, exist_ok=True)

                        # Save file directly using open/write method instead of save()
                        file_path = os.path.join(upload_folder, filename)
                        with open(file_path, 'wb') as f:
                            logo_file.save(f)

                        # Confirm file was saved
                        if os.path.exists(file_path):
                            flash('Logo uploaded successfully!', 'success')
                            print(f"Logo saved to: {file_path}")
                            # Optionally delete old logo file
                            if store.logo_filename and store.logo_filename != filename:
                                old_path = os.path.join(upload_folder, store.logo_filename)
                                try:
                                    if os.path.exists(old_path):
                                        os.remove(old_path)
                                except Exception:
                                    pass
                            store.logo_filename = filename
                        else:
                            flash('Logo upload failed - file not created.', 'danger')
                            print(f"Failed to save logo to: {file_path}")
                except Exception as e:
                    flash(f'Error uploading logo: {str(e)}', 'danger')
                    print(f"Exception during logo upload: {str(e)}")
                    return render_template('edit_store.html', store=store, form=form, errors=errors, title='Edit Store')
        # Password logic
        password = request.form.get('password', '')
        if password:
            if len(password) < 8:
                errors.append('Password must be at least 8 characters.')
            else:
                store.set_password(password)
        
        # Security question and answer logic
        security_question = request.form.get('security_question', '')
        security_answer = request.form.get('security_answer', '')
        
        # Update security question if provided
        if security_question:
            store.security_question = security_question
            
        # Update security answer if provided
        if security_answer:
            store.set_security_answer(security_answer)
        # Set all other fields
        store.name = request.form.get('name', store.name)
        store.username = new_username
        store.address = request.form.get('address', store.address)
        store.phone = request.form.get('phone', store.phone)
        store.email = email
        store.timezone = request.form.get('timezone', store.timezone)
        store.subscription_status = request.form.get('subscription_status', store.subscription_status)
        store.status = request.form.get('status', store.status)
        store.business_hours = request.form.get('business_hours', store.business_hours)
        store.description = request.form.get('description', store.description)
        store.facebook_url = request.form.get('facebook_url', store.facebook_url)
        store.instagram_url = request.form.get('instagram_url', store.instagram_url)
        store.website_url = request.form.get('website_url', store.website_url)
        store.tax_id = request.form.get('tax_id', store.tax_id)
        store.notification_preferences = request.form.get('notification_preferences', store.notification_preferences)
        try:
            store.default_appointment_duration = int(request.form.get('default_appointment_duration', store.default_appointment_duration) or 0) or None
        except ValueError:
            errors.append('Default appointment duration must be a number.')
        try:
            store.default_appointment_buffer = int(request.form.get('default_appointment_buffer', store.default_appointment_buffer) or 0) or None
        except ValueError:
            errors.append('Default appointment buffer must be a number.')
        store.payment_settings = request.form.get('payment_settings', store.payment_settings)
        store.is_archived = 'is_archived' in request.form
        # If errors, show them and don't commit
        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template('edit_store.html', store=store, timezones=timezones)
        # Audit log for sensitive changes
        if new_username != store.username:
            current_app.logger.info(f"[AUDIT] Store username changed for store {store.id}")
        if password:
            current_app.logger.info(f"[AUDIT] Store password changed for store {store.id}")
        try:
            db.session.commit()
            flash('Store information updated successfully.', 'success')
            return redirect(url_for('management.edit_store'))
        except Exception as e:
            db.session.rollback()
            flash('Failed to update store information.', 'danger')
    return render_template('edit_store.html', store=store, timezones=timezones)

def sync_google_calendar_for_store(store, user):
    if not store or not store.google_token_json or not store.google_calendar_id:
        current_app.logger.warning("[SYNC] Store missing Google token or calendar ID.")
        return 0
    try:
        # Use store's timezone if set, else default to UTC
        store_tz_str = getattr(store, 'timezone', None) or 'UTC'
        try:
            store_tz = pytz.timezone(store_tz_str)
        except Exception:
            store_tz = pytz.UTC
        token_data = json.loads(store.google_token_json)
        credentials = GoogleCredentials(
            token=token_data.get('token') or token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
            client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
            scopes=[
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.readonly",
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile"
            ]
        )
        service = build('calendar', 'v3', credentials=credentials)
        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
        now = now_utc.astimezone(store_tz).isoformat()
        events_result = service.events().list(
            calendarId=store.google_calendar_id,
            timeMin=now,
            maxResults=250,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        current_app.logger.info(f"[SYNC] Retrieved {len(events)} events from Google Calendar.")
        for event in events:
            current_app.logger.info(f"[SYNC] Event: id={event.get('id')}, summary={event.get('summary')}, description={event.get('description')}, start={event.get('start')}")
        created_appointments = []
        for event in events:
            details_needed = False
            missing_fields = []
            desc = event.get('description', '')
            # Parse fields from description using regex or simple search
            dog = owner = groomer = services = notes = None
            dog_match = re.search(r'Dog: ([^\n]+)', desc)
            owner_match = re.search(r'Owner: ([^\n]+)', desc)
            groomer_match = re.search(r'Groomer: ([^\n]+)', desc)
            services_match = re.search(r'Services: ([^\n]+)', desc)
            notes_match = re.search(r'Notes: ([^\n]+)', desc)
            status_match = re.search(r'Status: ([^\n]+)', desc)
            if dog_match:
                dog = dog_match.group(1).strip()
            if owner_match:
                owner = owner_match.group(1).strip()
            if groomer_match:
                groomer = groomer_match.group(1).strip()
            if services_match:
                services = services_match.group(1).strip()
            if notes_match:
                notes = notes_match.group(1).strip()
            status = status_match.group(1).strip() if status_match else 'Scheduled'
            # Check if the event is cancelled in Google Calendar
            is_cancelled = event.get('status', '').lower() == 'cancelled'
            # Parse start time
            start_str = event['start'].get('dateTime') or event['start'].get('date')
            appt_dt = None
            try:
                if start_str:
                    # Parse with timezone awareness
                    appt_dt = dateutil_parser.isoparse(start_str)
                    if appt_dt.tzinfo is None:
                        appt_dt = store_tz.localize(appt_dt)
                    # Always convert to UTC for storage
                    appt_dt = appt_dt.astimezone(pytz.UTC)
            except Exception:
                appt_dt = None
            # Skip if required info is missing or dog is a placeholder
            if not dog or dog == 'Unknown Dog':
                dog = 'Unknown Dog'
                missing_fields.append('dog')
            if not owner:
                owner = 'Unknown Owner'
                missing_fields.append('owner')
            if not appt_dt:
                # Use a far-future date as a placeholder if missing
                appt_dt = datetime.datetime(2099, 1, 1, tzinfo=pytz.UTC)
                missing_fields.append('date')
            if missing_fields:
                details_needed = True
                current_app.logger.warning(f"[SYNC] Event {event.get('id')} missing: {', '.join(missing_fields)}. Created/updated with placeholders and details_needed=True.")
            # Find or create owner (by full name or first name)
            owner_first = owner.split()[0]
            owner_obj = Owner.query.filter(
                Owner.store_id == store.id,
                or_(func.lower(Owner.name) == owner.lower(),
                    func.lower(func.substr(Owner.name, 1, func.instr(Owner.name, ' ') - 1)) == owner_first.lower() if owner_first else False)
            ).first()
            # --- BEGIN: Updated logic for unknown dog/owner ---
            owner_obj_found = True
            if not owner_obj:
                owner_obj_found = False
            dog_obj_found = True
            dog_first = dog.split()[0]
            dog_obj = None
            if owner_obj:
                dog_obj = Dog.query.filter(
                    Dog.owner_id == owner_obj.id,
                    Dog.store_id == store.id,
                    or_(func.lower(Dog.name) == dog.lower(),
                        func.lower(func.substr(Dog.name, 1, func.instr(Dog.name, ' ') - 1)) == dog_first.lower() if dog_first else False)
                ).first()
            if not dog_obj:
                dog_obj_found = False

            # If neither owner nor dog found, create both as unknown and link them
            if not owner_obj_found and not dog_obj_found:
                owner_obj = Owner(name="Unknown Owner", phone_number='000-000-0000', email='unknown@unknown.com', store_id=store.id)
                db.session.add(owner_obj)
                db.session.commit()
                dog_obj = Dog(name="Unknown Dog", owner_id=owner_obj.id, store_id=store.id)
                db.session.add(dog_obj)
                db.session.commit()
            else:
                # If only owner is missing, create owner as usual
                if not owner_obj_found:
                    owner_obj = Owner(name=owner, phone_number='000-000-0000', email='unknown@unknown.com', store_id=store.id)
                    try:
                        db.session.add(owner_obj)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                        details_needed = True
                        missing_fields.append('Owner')
                # If only dog is missing, create dog as usual **but skip if the dog name is the placeholder**
                if not dog_obj_found and dog.lower() != 'unknown dog':
                    dog_obj = Dog(name=dog, owner_id=owner_obj.id, store_id=store.id)
                    db.session.add(dog_obj)
                    db.session.commit()
                elif not dog_obj_found and dog.lower() == 'unknown dog':
                    # Do not create a placeholder dog record tied to a real owner; instead, flag that details are needed.
                    details_needed = True
                    missing_fields.append('dog')
            # --- END: Updated logic for unknown dog/owner ---
            # Find groomer (by full username or first name)
            groomer_obj = None
            if groomer:
                groomer_first = groomer.split()[0]
                groomer_obj = User.query.filter(
                    User.is_groomer == True,
                    User.store_id == store.id,
                    or_(func.lower(User.username) == groomer.lower(),
                        func.lower(func.substr(User.username, 1, func.instr(User.username, ' ') - 1)) == groomer_first.lower() if groomer_first else False)
                ).first()
            # Add missing info to notes
            notes_with_missing = notes or ''
            if status == 'Scheduled' and (not dog_obj or not owner_obj or not appt_dt):
                details_needed = True
                missing_fields = []
                if not dog_obj:
                    missing_fields.append('Dog')
                if not owner_obj:
                    missing_fields.append('Owner')
                if not appt_dt:
                    missing_fields.append('Date/Time')
            if details_needed and missing_fields:
                notes_with_missing += ('\n' if notes_with_missing else '') + f"[Needs Review: Missing {', '.join(missing_fields)}]"
            # Check if appointment already exists (by eventId and store_id)
            existing = Appointment.query.filter_by(
                store_id=store.id,
                google_event_id=event['id']
            ).first()
            if existing:
                # Only update fields that should be synced from Google
                existing.appointment_datetime = appt_dt
                
                # Don't update status to 'Cancelled' if it's already set to 'Completed' or 'No Show'
                if existing.status not in ['Completed', 'No Show']:
                    existing.status = 'Cancelled' if is_cancelled else status
                
                # Don't overwrite services and notes if they exist locally
                if not existing.requested_services_text and services:
                    existing.requested_services_text = services
                if not existing.notes and notes:
                    existing.notes = notes_with_missing
                    
                # Only set details_needed to True if it's not already set
                if not existing.details_needed:
                    existing.details_needed = details_needed
                    
                # Update the dog and groomer relationships if they're not set
                if not existing.dog_id and dog_obj:
                    existing.dog_id = dog_obj.id
                if not existing.groomer_id and groomer_obj:
                    existing.groomer_id = groomer_obj.id
                    
                if user and user.id and not existing.created_by_user_id:
                    existing.created_by_user_id = user.id
                    
                db.session.commit()
                current_app.logger.info(f"[SYNC] Updated existing appointment for Google event {event['id']} (store {store.id})")
            else:
                # Only create if not already present
                appt = Appointment(
                    dog_id=dog_obj.id,
                    appointment_datetime=appt_dt,
                    requested_services_text=services,
                    notes=notes_with_missing,
                    status=status,
                    created_by_user_id=user.id if user else None,
                    groomer_id=groomer_obj.id if groomer_obj else None,
                    store_id=store.id,
                    google_event_id=event['id'],
                    details_needed=details_needed
                )
                db.session.add(appt)
                db.session.commit()
                created_appointments.append(appt)
                current_app.logger.info(f"[SYNC] Created new appointment for Google event {event['id']} (store {store.id})")
        return len(created_appointments)
    except Exception as e:
        current_app.logger.error(f"Failed to sync Google Calendar: {e}", exc_info=True)
        return 0

@management_bp.route('/sync_google_calendar')
@admin_required
def sync_google_calendar():
    store_id = session.get('store_id')
    store = Store.query.get_or_404(store_id)
    num_synced = sync_google_calendar_for_store(store, g.user)
    if num_synced > 0:
        flash(f'Synced {num_synced} new appointments from Google Calendar.', 'success')
        log_activity(f'Synced {num_synced} appts from Google Calendar')
    else:
        flash('No new appointments to sync from Google Calendar.', 'info')
    return redirect(url_for('management.management'))


# --- Data Management Routes ---
@management_bp.route('/data_management')
@admin_required
def data_management():
    """Render the data management page for exporting/importing data."""
    store_id = session.get('store_id')
    store = Store.query.get_or_404(store_id) if store_id else None
    form = DatabaseImportForm()
    return render_template('data_management.html', form=form)


@management_bp.route('/data_management/export_database')
@admin_required
def export_database():
    """Export only the store's data as a database file."""
    store_id = session.get('store_id')
    store = Store.query.get_or_404(store_id) if store_id else None
    
    if not store:
        flash("Store not found.", "error")
        return redirect(url_for('management.data_management'))
    
    # Create a temporary database file for just this store's data
    temp_dir = tempfile.mkdtemp()
    temp_db_path = os.path.join(temp_dir, 'store_export.db')
    
    try:
        # Import sqlite3 module locally
        import sqlite3
        
        # Connect to the new temporary database
        new_conn = sqlite3.connect(temp_db_path)
        new_cursor = new_conn.cursor()
        
        # Create the schema in the new database
        # First, get table information from the current database
        source_engine = db.get_engine()
        with source_engine.connect() as connection:
            # Get all table names
            table_names_result = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
            table_names = [row[0] for row in table_names_result.fetchall()]
            
            # Also get the sqlite_sequence table (needed for auto-incrementing IDs)
            table_names.append('sqlite_sequence')
            
            # For each table, create it in the new database and copy data for the store
            for table_name in table_names:
                # Get table creation SQL (this requires raw SQL execution)
                create_table_sql_result = connection.execute(text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'"))
                create_sql = create_table_sql_result.fetchone()
                
                if create_sql and create_sql[0]:
                    # Create the table in the new database
                    new_cursor.execute(create_sql[0])
                    
                    # Check if table has store_id column to filter data
                    columns_info_result = connection.execute(text(f"PRAGMA table_info('{table_name}')"))
                    columns_info = columns_info_result.fetchall()
                    column_names = [col[1] for col in columns_info]
                    
                    if 'store_id' in column_names:
                        has_store_id = True
                        # Get data for this store only
                        rows_result = connection.execute(text(f"SELECT * FROM {table_name} WHERE store_id = {store_id}"))
                        rows = rows_result.fetchall()
                        
                        if rows:
                            # Prepare insert statement with the right number of placeholders
                            placeholders = ', '.join(['?' for _ in column_names])
                            insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
                            new_cursor.executemany(insert_sql, rows)
                    else:
                        # For tables without store_id, check if they are global tables that should be copied
                        # These might include configuration tables, etc.
                        if table_name in ['sqlite_sequence']:  # Add other global tables if needed
                            rows_result = connection.execute(text(f"SELECT * FROM {table_name}"))
                            rows = rows_result.fetchall()
                            
                            if rows:
                                placeholders = ', '.join(['?' for _ in range(len(rows[0]))])
                                insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
                                new_cursor.executemany(insert_sql, rows)
        
        # Commit changes and close the new database connection
        new_conn.commit()
        new_conn.close()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        store_name_safe = secure_filename(store.name)
        download_name = f"{store_name_safe}_database_{timestamp}.db"
        
        # Log activity
        log = ActivityLog(
            action="Store Database Exported",
            details=f"Store-specific database exported by user {g.user.username}",
            user_id=g.user.id,
            store_id=store_id
        )
        db.session.add(log)
        db.session.commit()
        
        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                current_app.logger.error(f"Error cleaning up temp directory: {e}")
            return response
        
        return send_file(temp_db_path, as_attachment=True, download_name=download_name)
    
    except Exception as e:
        current_app.logger.error(f"Error creating store database export: {e}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        flash(f"Error creating database export: {str(e)}", "error")
        return redirect(url_for('management.data_management'))


@management_bp.route('/data_management/export_images')
@admin_required
def export_images():
    """Export only the store's images as a zip file."""
    store_id = session.get('store_id')
    store = Store.query.get_or_404(store_id) if store_id else None
    
    if not store:
        flash("Store not found.", "error")
        return redirect(url_for('management.data_management'))
    
    upload_folder = current_app.config['UPLOAD_FOLDER']
    static_folder = current_app.static_folder
    
    if not os.path.exists(upload_folder):
        flash("Upload folder not found.", "error")
        return redirect(url_for('management.data_management'))
    
    # Collect all image filenames for this store from database
    store_images = set()
    
    # 1. Get store logo filename if exists
    if store.logo_filename:
        store_images.add(store.logo_filename)
    
    # 2. Get all user profile pictures for this store
    users = User.query.filter_by(store_id=store_id).all()
    for user in users:
        if user.picture_filename:
            store_images.add(user.picture_filename)
    
    # 3. Get all dog pictures for this store
    dogs = Dog.query.filter_by(store_id=store_id).all()
    for dog in dogs:
        if dog.picture_filename:
            store_images.add(dog.picture_filename)
    
    # Create temp directory for zip
    temp_dir = tempfile.mkdtemp()
    temp_zip_path = os.path.join(temp_dir, 'images.zip')
    
    try:
        # Track found images to report any missing files
        images_found = 0
        images_missing = 0
        
        with zipfile.ZipFile(temp_zip_path, 'w') as zipf:
            # First check the main uploads folder
            if os.path.exists(upload_folder):
                for root, _, files in os.walk(upload_folder):
                    for file in files:
                        # Check if this file is in our store's image set
                        if file in store_images:
                            file_path = os.path.join(root, file)
                            rel_path = os.path.join('uploads', os.path.relpath(file_path, upload_folder))
                            zipf.write(file_path, rel_path)
                            images_found += 1
            
            # Also check static/uploads folders for store logos
            static_uploads = os.path.join(static_folder, 'uploads')
            if os.path.exists(static_uploads):
                for root, _, files in os.walk(static_uploads):
                    for file in files:
                        if file in store_images:
                            file_path = os.path.join(root, file)
                            # Get path relative to static folder
                            rel_path = os.path.relpath(file_path, static_folder)
                            zipf.write(file_path, rel_path)
                            images_found += 1
        
        # Check if we found any images
        if images_found == 0:
            flash("No images found for this store.", "warning")
            shutil.rmtree(temp_dir)
            return redirect(url_for('management.data_management'))
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        store_name_safe = secure_filename(store.name)
        download_name = f"{store_name_safe}_images_{timestamp}.zip"
        
        # Log activity
        log = ActivityLog(
            action="Store Images Exported",
            details=f"Store-specific images ({images_found} files) exported by user {g.user.username}",
            user_id=g.user.id,
            store_id=store_id
        )
        db.session.add(log)
        db.session.commit()
        
        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                current_app.logger.error(f"Error cleaning up temp directory: {e}")
            return response
        
        return send_file(temp_zip_path, as_attachment=True, download_name=download_name)
    
    except Exception as e:
        current_app.logger.error(f"Error creating store images export: {e}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        flash(f"Error creating images export: {str(e)}", "error")
        return redirect(url_for('management.data_management'))


@management_bp.route('/data_management/export_all_data')
@admin_required
def export_all_data():
    """Export both store-specific database and images as a single zip file."""
    store_id = session.get('store_id')
    store = Store.query.get_or_404(store_id) if store_id else None
    
    if not store:
        flash("Store not found.", "error")
        return redirect(url_for('management.data_management'))
    
    upload_folder = current_app.config['UPLOAD_FOLDER']
    
    if not os.path.exists(upload_folder):
        flash("Upload folder not found.", "error")
        return redirect(url_for('management.data_management'))
    
    # Create a temporary directory
    temp_dir = tempfile.mkdtemp()
    temp_zip_path = os.path.join(temp_dir, 'all_data.zip')
    temp_db_path = os.path.join(temp_dir, 'store_export.db')
    
    try:
        # Create store-specific database file
        import sqlite3
        
        # Connect to the new temporary database
        new_conn = sqlite3.connect(temp_db_path)
        new_cursor = new_conn.cursor()
        
        # Create the schema in the new database
        source_engine = db.get_engine()
        with source_engine.connect() as connection:
            # Get all table names
            table_names_result = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
            table_names = [row[0] for row in table_names_result.fetchall()]
            
            # Also get the sqlite_sequence table (needed for auto-incrementing IDs)
            table_names.append('sqlite_sequence')
            
            # For each table, create it in the new database and copy data for the store
            for table_name in table_names:
                # Get table creation SQL
                create_table_sql_result = connection.execute(text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'"))
                create_sql = create_table_sql_result.fetchone()
                
                if create_sql and create_sql[0]:
                    # Create the table in the new database
                    new_cursor.execute(create_sql[0])
                    
                    # Check if table has store_id column to filter data
                    columns_info_result = connection.execute(text(f"PRAGMA table_info('{table_name}')"))
                    columns_info = columns_info_result.fetchall()
                    column_names = [col[1] for col in columns_info]
                    
                    if 'store_id' in column_names:
                        # Get data for this store only
                        rows = connection.execute(f"SELECT * FROM {table_name} WHERE store_id = {store_id}").fetchall()
                        
                        if rows:
                            # Prepare insert statement with the right number of placeholders
                            placeholders = ', '.join(['?' for _ in column_names])
                            insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
                            
                            # Insert the data
                            new_cursor.executemany(insert_sql, rows)
                    else:
                        # For tables without store_id, check if they are global tables that should be copied
                        if table_name in ['sqlite_sequence']:  # Add other global tables if needed
                            rows = connection.execute(f"SELECT * FROM {table_name}").fetchall()
                            
                            if rows:
                                placeholders = ', '.join(['?' for _ in range(len(rows[0]))])
                                insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
                                new_cursor.executemany(insert_sql, rows)
        
        # Commit changes and close the new database connection
        new_conn.commit()
        new_conn.close()
        
        # Now create the zip file with both the database and images
        with zipfile.ZipFile(temp_zip_path, 'w') as zipf:
            # Add the store-specific database file
            db_filename = f"{secure_filename(store.name)}_database.db"
            zipf.write(temp_db_path, db_filename)
            
            # Collect all image filenames for this store from database
            store_images = set()
            
            # 1. Get store logo filename if exists
            if store.logo_filename:
                store_images.add(store.logo_filename)
            
            # 2. Get all user profile pictures for this store
            users = User.query.filter_by(store_id=store_id).all()
            for user in users:
                if user.picture_filename:
                    store_images.add(user.picture_filename)
            
            # 3. Get all dog pictures for this store
            dogs = Dog.query.filter_by(store_id=store_id).all()
            for dog in dogs:
                if dog.picture_filename:
                    store_images.add(dog.picture_filename)
            
            # Track found images count
            images_found = 0
            
            # Add images from uploads folder
            if os.path.exists(upload_folder):
                for root, _, files in os.walk(upload_folder):
                    for file in files:
                        # Check if this file is in our store's image set
                        if file in store_images:
                            file_path = os.path.join(root, file)
                            rel_path = os.path.join('uploads', os.path.relpath(file_path, upload_folder))
                            zipf.write(file_path, rel_path)
                            images_found += 1
            
            # Also check static/uploads folders for store logos
            static_uploads = os.path.join(current_app.static_folder, 'uploads')
            if os.path.exists(static_uploads):
                for root, _, files in os.walk(static_uploads):
                    for file in files:
                        if file in store_images:
                            file_path = os.path.join(root, file)
                            # Get path relative to static folder
                            rel_path = os.path.relpath(file_path, current_app.static_folder)
                            zipf.write(file_path, rel_path)
                            images_found += 1
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        store_name_safe = secure_filename(store.name)
        download_name = f"{store_name_safe}_all_data_{timestamp}.zip"
        
        # Log activity
        log = ActivityLog(
            action="Store Data Exported",
            details=f"Store-specific data export by user {g.user.username}",
            user_id=g.user.id,
            store_id=store_id
        )
        db.session.add(log)
        db.session.commit()
        
        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                current_app.logger.error(f"Error cleaning up temp directory: {e}")
            return response
        
        return send_file(temp_zip_path, as_attachment=True, download_name=download_name)
    
    except Exception as e:
        current_app.logger.error(f"Error creating all data export: {e}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        flash(f"Error creating data export: {str(e)}", "error")
        return redirect(url_for('management.data_management'))


@management_bp.route('/data_management/import_database', methods=['POST'])
@admin_required
def import_database():
    """Import a database file, either overwriting or merging with the current one."""
    form = DatabaseImportForm()
    
    if form.validate_on_submit():
        try:
            # Get import mode (overwrite or merge)
            import_mode = request.form.get('import_mode', 'overwrite')
            
            # Get the current database path
            db_path = current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
            
            # Create a backup of the current database
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{db_path}.backup_{timestamp}"
            shutil.copy2(db_path, backup_path)
            
            # Get the uploaded file
            uploaded_file = form.database_file.data
            
            # Save the uploaded file to a temporary location
            temp_dir = tempfile.mkdtemp()
            temp_db_path = os.path.join(temp_dir, 'uploaded_database.db')
            uploaded_file.save(temp_db_path)
            
            # Process based on import mode
            if import_mode == 'overwrite':
                # Close database connections before replacing the file
                db.session.close()
                db.engine.dispose()
                
                # Overwrite mode - simply replace the current database
                shutil.copy2(temp_db_path, db_path)
                
                action_details = "Database completely overwritten"
                flash_message = "Database replaced successfully! The application will log you out to apply changes."
            else:  # merge mode
                # Merge the uploaded database with the current one
                try:
                    # Open connections to both databases
                    current_conn = sqlite3.connect(db_path)
                    current_cursor = current_conn.cursor()
                    imported_conn = sqlite3.connect(temp_db_path)
                    imported_cursor = imported_conn.cursor()
                    
                    # Get store ID for filtering imported data
                    store_id = session.get('store_id')
                    
                    # Get all tables from the imported database
                    imported_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                    imported_tables = [row[0] for row in imported_cursor.fetchall()]
                    
                    # For each table in the imported database
                    tables_updated = []
                    records_added = 0
                    
                    for table_name in imported_tables:
                        # Check if the table exists in the current database
                        current_cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                        if not current_cursor.fetchone():
                            # Table doesn't exist in current database, skip it
                            current_app.logger.warning(f"Table {table_name} not found in current database, skipping")
                            continue
                        
                        # Get the primary key column(s) for the table
                        current_cursor.execute(f"PRAGMA table_info('{table_name}')")
                        columns_info = current_cursor.fetchall()
                        primary_key_columns = [col[1] for col in columns_info if col[5] > 0]  # col[5] > 0 means primary key
                        column_names = [col[1] for col in columns_info]
                        
                        # If no primary key, use all columns as composite key for uniqueness check
                        if not primary_key_columns:
                            primary_key_columns = column_names
                            
                        # Only import data related to this store if store_id is present
                        has_store_id = 'store_id' in column_names
                        
                        # Get data from imported database
                        if has_store_id:
                            imported_cursor.execute(f"SELECT * FROM {table_name} WHERE store_id = {store_id}")
                        else:
                            # For global tables, only get them if they're in our allowlist
                            if table_name in ['sqlite_sequence']:
                                imported_cursor.execute(f"SELECT * FROM {table_name}")
                            else:
                                # Skip tables without store_id that aren't in our allowlist
                                continue
                                
                        imported_rows = imported_cursor.fetchall()
                        if not imported_rows:
                            continue
                            
                        # For each imported row, check if it already exists in the current database
                        table_updated = False
                        for row in imported_rows:
                            # Build a WHERE clause to check for duplicates based on primary key(s)
                            where_conditions = []
                            for i, col_name in enumerate(column_names):
                                if col_name in primary_key_columns:
                                    # Handle NULL values in the primary key
                                    if row[i] is None:
                                        where_conditions.append(f"{col_name} IS NULL")
                                    else:
                                        where_conditions.append(f"{col_name} = ?")
                            
                            # If we have where conditions, check for duplicates
                            if where_conditions:
                                where_clause = " AND ".join(where_conditions)
                                where_values = [row[i] for i, col_name in enumerate(column_names) 
                                               if col_name in primary_key_columns and row[i] is not None]
                                
                                current_cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {where_clause}", where_values)
                                if current_cursor.fetchone()[0] == 0:
                                    # No duplicate found, insert the row
                                    placeholders = ', '.join(['?' for _ in column_names])
                                    current_cursor.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", row)
                                    records_added += 1
                                    table_updated = True
                            else:
                                # No primary key to check duplicates, just insert
                                placeholders = ', '.join(['?' for _ in column_names])
                                current_cursor.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", row)
                                records_added += 1
                                table_updated = True
                        
                        if table_updated:
                            tables_updated.append(table_name)
                    
                    # Commit all changes
                    current_conn.commit()
                    
                    action_details = f"Database merged: {records_added} records added across {len(tables_updated)} tables"
                    flash_message = f"Database merged successfully! Added {records_added} records to {len(tables_updated)} tables. The application will log you out to apply changes."
                    
                except Exception as merge_error:
                    current_app.logger.error(f"Error merging databases: {merge_error}")
                    raise Exception(f"Error merging databases: {merge_error}")
                finally:
                    # Close connections
                    try:
                        current_cursor.close()
                        current_conn.close()
                        imported_cursor.close()
                        imported_conn.close()
                    except Exception as close_error:
                        current_app.logger.error(f"Error closing database connections: {close_error}")
            
            # Log the activity
            try:
                store_id = session.get('store_id')
                log = ActivityLog(
                    action=f"Database Imported ({import_mode})",
                    details=f"Database import ({import_mode}) by {g.user.username}. {action_details}. Backup at {backup_path}",
                    user_id=g.user.id,
                    store_id=store_id
                )
                
                # Reopen connection for logging
                db.session.close()
                db.engine.dispose()
                db.create_all()
                db.session.add(log)
                db.session.commit()
            except Exception as log_error:
                # If logging fails, continue with import but notify about the error
                current_app.logger.error(f"Failed to log import activity: {log_error}")
                flash(f"Database import succeeded, but could not log activity: {str(log_error)}", "warning")
            
            # Clean up temp directory
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                current_app.logger.error(f"Error cleaning up temp directory: {cleanup_error}")
            
            flash(flash_message, "success")
            return redirect(url_for('auth.logout'))
            
        except Exception as e:
            current_app.logger.error(f"Error importing database: {e}")
            flash(f"Error importing database: {str(e)}", "error")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", "error")
    
    return redirect(url_for('management.data_management'))
