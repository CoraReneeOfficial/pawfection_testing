from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app, session, abort
from models import User, Service, Appointment, ActivityLog, Store
from extensions import db
from sqlalchemy.exc import IntegrityError
from decimal import Decimal, InvalidOperation
from functools import wraps
import datetime
from datetime import timezone, timedelta
import calendar
import os
import uuid
from utils import allowed_file, log_activity
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import json

management_bp = Blueprint('management', __name__)

# --- Helpers ---
NOTIFICATION_SETTINGS_FILE = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'notification_settings.json')

# Decorator for admin routes
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, 'user') or g.user is None or not g.user.is_admin:
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def load_notification_preferences():
    # This should be adapted to use current_app context if needed
    pass  # Placeholder for actual implementation

def save_notification_preferences():
    # This should be adapted to use current_app context if needed
    pass  # Placeholder for actual implementation

def _handle_user_picture_upload(user_instance, request_files):
    if 'user_picture' not in request_files: return None
    file = request_files['user_picture']
    if file and file.filename != '' and '.' in file.filename:
        ext = file.filename.rsplit('.', 1)[1].lower()
        new_filename = f"user_{user_instance.id or 'temp'}_{uuid.uuid4().hex[:8]}.{ext}"
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], new_filename)
        os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
        if user_instance.picture_filename and user_instance.picture_filename != new_filename:
            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], user_instance.picture_filename)
            if os.path.exists(old_path):
                try: os.remove(old_path); current_app.logger.info(f"Deleted old user pic: {old_path}")
                except OSError as e_rem: current_app.logger.error(f"Could not delete old user pic {old_path}: {e_rem}")
        try:
            file.save(file_path); current_app.logger.info(f"Saved new user pic: {file_path}"); return new_filename
        except Exception as e_save:
            flash(f"Failed to save user picture: {e_save}", "warning")
            current_app.logger.error(f"Failed to save user pic {file_path}: {e_save}", exc_info=True)
    elif file and file.filename != '': flash("Invalid file type for user picture.", "warning")
    return None

def get_date_range(range_type, start_date_str=None, end_date_str=None):
    BUSINESS_TIMEZONE = timezone.utc  # Replace with actual timezone logic if needed
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

# --- Management Routes ---
@management_bp.route('/management')
@admin_required
def management():
    log_activity("Viewed Management page")
    # Determine Google connection status for the current store
    store = None
    is_google_calendar_connected = False
    is_gmail_for_sending_connected = False
    if hasattr(g, 'user') and g.user and g.user.store_id:
        store = Store.query.get(g.user.store_id)
        if store and store.google_token_json:
            try:
                token_data = json.loads(store.google_token_json)
                scopes = token_data.get('scopes', [])
                is_google_calendar_connected = 'https://www.googleapis.com/auth/calendar' in scopes
                is_gmail_for_sending_connected = 'https://www.googleapis.com/auth/gmail.send' in scopes
            except Exception:
                pass
    return render_template('management.html',
        is_google_calendar_connected=is_google_calendar_connected,
        is_gmail_for_sending_connected=is_gmail_for_sending_connected)

@management_bp.route('/manage/users')
@admin_required
def manage_users():
    log_activity("Viewed User Management page")
    users = User.query.order_by(User.username).all()
    return render_template('manage_users.html', users=users)

@management_bp.route('/manage/users/add', methods=['GET', 'POST'])
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
            flash(f"User '{username}' added.", "success"); return redirect(url_for('management.manage_users'))
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"Error adding user: {e}", exc_info=True)
            flash("Error adding user.", "danger")
            form_data = request.form.to_dict()
            form_data['is_admin'] = is_admin; form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='add', user_data=form_data), 500
    log_activity("Viewed Add User page")
    return render_template('user_form.html', mode='add', user_data={'is_groomer': True}) 

@management_bp.route('/manage/users/<int:user_id>/edit', methods=['GET', 'POST'])
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
            flash(f"User '{new_username}' updated.", "success"); return redirect(url_for('management.manage_users'))
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"Error updating user {user_id}: {e}", exc_info=True)
            flash("Error updating user.", "danger")
            form_data = request.form.to_dict(); form_data['id'] = user_id; form_data['picture_filename'] = user_to_edit.picture_filename
            form_data['is_admin'] = is_admin; form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='edit', user_data=form_data), 500
    log_activity("Viewed Edit User page", details=f"User ID: {user_id}")
    return render_template('user_form.html', mode='edit', user_data=user_to_edit) 

@management_bp.route('/manage/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.id == g.user.id:
        flash("Cannot delete own account.", "danger"); return redirect(url_for('management.manage_users'))
    if user_to_delete.is_admin and User.query.filter_by(is_admin=True).count() <= 1:
        flash("Cannot delete last admin.", "danger"); return redirect(url_for('management.manage_users'))
    username_deleted = user_to_delete.username
    pic_to_delete = user_to_delete.picture_filename
    try:
        Appointment.query.filter_by(groomer_id=user_id).update({'groomer_id': None})
        db.session.delete(user_to_delete); db.session.commit()
        if pic_to_delete:
            path = os.path.join(current_app.config['UPLOAD_FOLDER'], pic_to_delete)
            if os.path.exists(path):
                try: os.remove(path); current_app.logger.info(f"Deleted user pic: {path}")
                except OSError as e_rem: current_app.logger.error(f"Error deleting user pic file {path}: {e_rem}")
        log_activity("Deleted User", details=f"Username: {username_deleted}")
        flash(f"User '{username_deleted}' deleted.", "success")
    except IntegrityError as ie:
        db.session.rollback(); current_app.logger.error(f"IntegrityError deleting user '{username_deleted}': {ie}", exc_info=True)
        flash(f"Could not delete '{username_deleted}'. Associated records might exist.", "danger")
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error deleting user '{username_deleted}': {e}", exc_info=True)
        flash(f"Error deleting '{username_deleted}'.", "danger")
    return redirect(url_for('management.manage_users'))

@management_bp.route('/manage/services')
@admin_required
def manage_services():
    log_activity("Viewed Service/Fee Management page")
    all_items = Service.query.order_by(Service.item_type, Service.name).all()
    services = [item for item in all_items if item.item_type == 'service']
    fees = [item for item in all_items if item.item_type == 'fee']
    return render_template('manage_services.html', services=services, fees=fees)

@management_bp.route('/manage/services/add', methods=['GET', 'POST'])
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
            flash(f"{item_type.capitalize()} '{name}' added.", "success"); return redirect(url_for('management.manage_services'))
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"Error adding {item_type}: {e}", exc_info=True)
            flash(f"Error adding {item_type}.", "danger"); return render_template('service_form.html', mode='add', item_data=request.form.to_dict()), 500
    log_activity("Viewed Add Service/Fee page")
    return render_template('service_form.html', mode='add', item_data={})

@management_bp.route('/manage/services/<int:service_id>/edit', methods=['GET', 'POST'])
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
            flash(f"{item_type.capitalize()} '{name}' updated.", "success"); return redirect(url_for('management.manage_services'))
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"Error editing item {service_id}: {e}", exc_info=True)
            flash(f"Error updating {item_type}.", "danger")
            form_data = request.form.to_dict(); form_data['id'] = service_id
            return render_template('service_form.html', mode='edit', item_data=form_data), 500
    log_activity(f"Viewed Edit {item_to_edit.item_type.capitalize()} page", details=f"ID: {service_id}")
    return render_template('service_form.html', mode='edit', item_data=item_to_edit)

@management_bp.route('/manage/services/<int:service_id>/delete', methods=['POST'])
@admin_required
def delete_service(service_id):
    item_to_delete = Service.query.get_or_404(service_id)
    item_name = item_to_delete.name; item_type = item_to_delete.item_type
    try:
        db.session.delete(item_to_delete); db.session.commit()
        log_activity(f"Deleted {item_type.capitalize()}", details=f"ID: {service_id}, Name: {item_name}")
        flash(f"{item_type.capitalize()} '{item_name}' deleted.", "success")
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error deleting {item_type} '{item_name}': {e}", exc_info=True)
        flash(f"Error deleting '{item_name}'. It might be in use.", "danger")
    return redirect(url_for('management.manage_services'))

@management_bp.route('/manage/reports', methods=['GET', 'POST'])
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
                except InvalidOperation: current_app.logger.warning(f"Invalid checkout_total_amount for Appt {appt.id}")
            
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

@management_bp.route('/manage/notifications', methods=['GET', 'POST'])
@admin_required
def manage_notifications():
    # You may need to adapt NOTIFICATION_PREFERENCES and helpers to work in blueprint context
    NOTIFICATION_PREFERENCES = current_app.config.get('NOTIFICATION_PREFERENCES', {})
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
        
        save_notification_preferences() 
        log_activity("Updated Notification Settings", details=str(NOTIFICATION_PREFERENCES))
        flash("Notification settings updated successfully!", "success")
        return redirect(url_for('management.manage_notifications'))
            
    load_notification_preferences() 
    log_activity("Viewed Manage Customer Notifications page")
    return render_template('manage_notifications.html', current_settings=NOTIFICATION_PREFERENCES)

@management_bp.route('/logs')
@admin_required
def view_logs():
    log_activity("Viewed Activity Log page")
    page = request.args.get('page', 1, type=int); per_page = 50
    logs_pagination = ActivityLog.query.options(db.joinedload(ActivityLog.user)).order_by(ActivityLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('logs.html', logs_pagination=logs_pagination)

@management_bp.route('/google/authorize')
@admin_required
def google_authorize():
    # Only allow admin users
    if not g.user or not g.user.is_admin:
        flash("Only administrators can connect Google services.", "danger")
        return redirect(url_for('management.management'))

    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI')
    if not client_id or not client_secret or not redirect_uri:
        flash("Google OAuth environment variables are not set.", "danger")
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
        prompt='consent'
    )
    session['google_oauth_state'] = state
    return redirect(authorization_url)

@management_bp.route('/google/oauth2callback')
@admin_required
def google_oauth2callback():
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI')
    if not client_id or not client_secret or not redirect_uri:
        flash("Google OAuth environment variables are not set.", "danger")
        return redirect(url_for('management.management'))

    state = session.get('google_oauth_state')
    if not state:
        flash("OAuth state missing. Please try again.", "danger")
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

    credentials = flow.credentials
    token_data = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    # Save token to the current store
    if hasattr(g, 'user') and g.user and g.user.store_id:
        store = Store.query.get(g.user.store_id)
        if store:
            store.google_token_json = json.dumps(token_data)
            try:
                db.session.commit()
                log_activity("Connected Google Account for Calendar/Gmail")
                flash("Google account connected successfully!", "success")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Failed to save Google token to store: {e}", exc_info=True)
                flash("Failed to save Google token.", "danger")
        else:
            flash("Store not found. Cannot save Google token.", "danger")
    else:
        flash("No store context. Cannot save Google token.", "danger")
    return redirect(url_for('management.management')) 