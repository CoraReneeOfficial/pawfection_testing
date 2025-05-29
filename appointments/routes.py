from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify, current_app, session
from models import Appointment, Dog, Owner, User, ActivityLog, Store
from extensions import db
from sqlalchemy import or_
from functools import wraps
import datetime
from datetime import timezone
from dateutil import tz, parser as dateutil_parser
from utils import allowed_file # Keep allowed_file from utils
from app import log_activity   # IMPORT log_activity from app.py
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json

appointments_bp = Blueprint('appointments', __name__)

BUSINESS_TIMEZONE_NAME = 'America/New_York'
BUSINESS_TIMEZONE = tz.gettz(BUSINESS_TIMEZONE_NAME)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile"
]

# The log_activity function definition has been removed from here as it's now in app.py
# def log_activity(action, details=None):
#     """
#     Logs user activity to the database.
#     Ensures that activity is logged only if a user is available in the global context.
#     """
#     if hasattr(g, 'user') and g.user:
#         try:
#             log_entry = ActivityLog(user_id=g.user.id, action=action, details=details)
#             db.session.add(log_entry)
#             db.session.commit()
#         except Exception as e:
#             db.session.rollback()
#             current_app.logger.error(f"Error logging activity: {e}", exc_info=True)
#     else:
#         current_app.logger.warning(f"Attempted to log activity '{action}' but no user in g.")

@appointments_bp.route('/calendar')
def calendar_view():
    """
    Displays the calendar view of appointments.
    Filters appointments by the current store's ID.
    """
    log_activity("Viewed Calendar page")
    # Retrieve the current store_id from the session
    store_id = session.get('store_id')
    
    local_appointments = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter(
        Appointment.status == 'Scheduled',
        Appointment.store_id == store_id  # Filter appointments by the current store
    ).order_by(Appointment.appointment_datetime.asc()).all()
    
    return render_template('calendar.html', local_appointments=local_appointments)

@appointments_bp.route('/api/appointments')
def api_appointments():
    """
    Provides appointment data in JSON format for the calendar view.
    Filters appointments by the current store's ID and date range.
    """
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    # Retrieve the current store_id from the session
    store_id = session.get('store_id')

    try:
        start_dt = dateutil_parser.isoparse(start_str).astimezone(timezone.utc) if start_str else None
        end_dt = dateutil_parser.isoparse(end_str).astimezone(timezone.utc) if end_str else None
    except ValueError:
        return jsonify({"error": "Invalid date format."}), 400

    query = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter(
        Appointment.store_id == store_id  # Filter appointments by the current store
    )

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
            "id": appt.id, 
            "title": title, 
            "start": appt.appointment_datetime.isoformat(), 
            "end": (appt.appointment_datetime + datetime.timedelta(hours=1)).isoformat(), 
            "allDay": False, 
            "dog_id": appt.dog_id, 
            "dog_name": appt.dog.name, 
            "owner_name": appt.dog.owner.name, 
            "groomer_name": appt.groomer.username if appt.groomer else "Unassigned",
            "status": appt.status, 
            "notes": appt.notes, 
            "services": appt.requested_services_text,
            "url": url_for('appointments.edit_appointment', appointment_id=appt.id), 
            "color": event_color,
            "borderColor": event_color 
        })
    return jsonify(events)

@appointments_bp.route('/add_appointment', methods=['GET', 'POST'])
def add_appointment():
    """
    Handles adding a new appointment.
    Ensures that only dogs and groomers from the current store are available for selection.
    Assigns the current store's ID to the new appointment.
    """
    store_id = session.get('store_id')  # Get store_id from session

    # Filter dogs and groomers by the current store
    dogs = Dog.query.options(db.joinedload(Dog.owner)).filter_by(store_id=store_id).order_by(Dog.name).all()
    groomers_for_dropdown = User.query.filter_by(is_groomer=True, store_id=store_id).order_by(User.username).all()

    if request.method == 'POST':
        dog_id_str = request.form.get('dog_id')
        date_str = request.form.get('appointment_date')
        time_str = request.form.get('appointment_time')
        services_text = request.form.get('services_text', '').strip()
        notes = request.form.get('notes', '').strip()
        groomer_id_str = request.form.get('groomer_id')
        
        errors = {}
        if not dog_id_str: errors['dog'] = "Dog required."
        if not date_str: errors['date'] = "Date required."
        if not time_str: errors['time'] = "Time required."
        
        utc_dt = None
        local_dt_for_log = None
        try:
            naive_dt = datetime.datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
            local_dt_for_log = naive_dt.replace(tzinfo=BUSINESS_TIMEZONE) 
            utc_dt = local_dt_for_log.astimezone(timezone.utc)
        except ValueError:
            errors['datetime_format'] = "Invalid date/time format."
        
        dog_id = int(dog_id_str) if dog_id_str and dog_id_str.isdigit() else None
        selected_dog = Dog.query.get(dog_id) if dog_id else None
        
        # Verify selected dog belongs to the current store
        if not selected_dog or selected_dog.store_id != store_id:
            errors['dog_invalid'] = "Dog not found or does not belong to this store."
        
        groomer_id = int(groomer_id_str) if groomer_id_str and groomer_id_str.isdigit() else None
        # Verify selected groomer belongs to the current store
        if groomer_id:
            selected_groomer = User.query.get(groomer_id)
            if not selected_groomer or selected_groomer.store_id != store_id:
                errors['groomer_invalid'] = "Groomer not found or does not belong to this store."

        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            return render_template('add_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=request.form.to_dict()), 400
        
        new_appt = Appointment(
            dog_id=selected_dog.id, 
            appointment_datetime=utc_dt, 
            requested_services_text=services_text or None, 
            notes=notes or None, 
            status='Scheduled', 
            created_by_user_id=g.user.id, 
            groomer_id=groomer_id,
            store_id=store_id  # Ensure store_id is correctly assigned to the new appointment
        )
        
        try:
            db.session.add(new_appt)
            db.session.commit()
            log_activity("Added Local Appt", details=f"Dog: {selected_dog.name}, Time: {local_dt_for_log.strftime('%Y-%m-%d %I:%M %p %Z') if local_dt_for_log else 'N/A'}")
            
            # --- Google Calendar Sync ---
            store = Store.query.get(g.user.store_id)
            if store and store.google_token_json:
                try:
                    token_data = json.loads(store.google_token_json)
                    credentials = Credentials(
                        token=token_data['token'],
                        refresh_token=token_data.get('refresh_token'),
                        token_uri=token_data['token_uri'],
                        client_id=token_data['client_id'],
                        client_secret=token_data['client_secret'],
                        scopes=SCOPES
                    )
                    service = build('calendar', 'v3', credentials=credentials)
                    event = {
                        'summary': f"{selected_dog.name} ({selected_dog.owner.name}) Appointment",
                        'description': notes or '',
                        'start': {'dateTime': utc_dt.isoformat(), 'timeZone': 'UTC'},
                        'end': {'dateTime': (utc_dt + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'UTC'},
                    }
                    created_event = service.events().insert(calendarId='primary', body=event).execute()
                    new_appt.google_event_id = created_event.get('id')
                    db.session.commit()
                    flash("Appointment synced to Google Calendar.", "success")
                except Exception as e:
                    current_app.logger.error(f"Google Calendar sync failed: {e}", exc_info=True)
                    flash("Appointment saved, but failed to sync with Google Calendar.", "warning")
            else:
                flash("Appointment saved, but Google Calendar is not connected for this store.", "info")
            
            return redirect(url_for('appointments.calendar_view'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding appt: {e}", exc_info=True)
            flash("Error adding appointment.", "danger")
            return render_template('add_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=request.form.to_dict()), 500
    
    log_activity("Viewed Add Appointment page")
    return render_template('add_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data={})

@appointments_bp.route('/appointment/<int:appointment_id>/edit', methods=['GET', 'POST'])
def edit_appointment(appointment_id):
    """
    Handles editing an existing appointment.
    Ensures that only appointments, dogs, and groomers from the current store are accessible.
    """
    store_id = session.get('store_id')  # Get store_id from session

    # Fetch the appointment, ensuring it belongs to the current store
    appt = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter_by(
        store_id=store_id  # Filter appointment by the current store
    ).get_or_404(appointment_id)

    # Filter dogs and groomers by the current store for dropdowns
    dogs = Dog.query.options(db.joinedload(Dog.owner)).filter_by(store_id=store_id).order_by(Dog.name).all()
    groomers_for_dropdown = User.query.filter_by(is_groomer=True, store_id=store_id).order_by(User.username).all()

    if request.method == 'POST':
        dog_id_str = request.form.get('dog_id')
        date_str = request.form.get('appointment_date')
        time_str = request.form.get('appointment_time')
        services_text = request.form.get('services_text', '').strip()
        notes = request.form.get('notes', '').strip()
        status = request.form.get('status', 'Scheduled').strip()
        groomer_id_str = request.form.get('groomer_id')
        
        errors = {}
        if status not in ['Scheduled', 'Completed', 'Cancelled', 'No Show']: errors['status'] = "Invalid status."
        
        utc_dt = None
        local_dt_for_log = None 
        try:
            naive_dt = datetime.datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
            local_dt_for_log = naive_dt.replace(tzinfo=BUSINESS_TIMEZONE)
            utc_dt = local_dt_for_log.astimezone(timezone.utc)
        except ValueError:
            errors['datetime_format'] = "Invalid date/time format."
        
        dog_id = int(dog_id_str) if dog_id_str and dog_id_str.isdigit() else None
        selected_dog = Dog.query.get(dog_id) if dog_id else None
        
        # Verify selected dog belongs to the current store
        if not selected_dog or selected_dog.store_id != store_id:
            errors['dog_invalid'] = "Dog not found or does not belong to this store."

        groomer_id = int(groomer_id_str) if groomer_id_str and groomer_id_str.isdigit() else None
        # Verify selected groomer belongs to the current store
        if groomer_id:
            selected_groomer = User.query.get(groomer_id)
            if not selected_groomer or selected_groomer.store_id != store_id:
                errors['groomer_invalid'] = "Groomer not found or does not belong to this store."

        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict()
            form_data.update({'id': appointment_id, 'dog': appt.dog, 'groomer': appt.groomer})
            return render_template('edit_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=form_data, appointment_id=appointment_id), 400
        
        appt.dog_id = selected_dog.id if selected_dog else appt.dog_id
        appt.appointment_datetime = utc_dt if utc_dt else appt.appointment_datetime
        appt.requested_services_text = services_text or None
        appt.notes = notes or None
        appt.status = status
        appt.groomer_id = groomer_id
        
        try:
            db.session.commit()
            log_activity("Edited Local Appt", details=f"Appt ID: {appointment_id}, Status: {status}, Time: {local_dt_for_log.strftime('%Y-%m-%d %I:%M %p %Z') if local_dt_for_log else 'N/A'}")
            
            # --- Google Calendar Sync ---
            store = Store.query.get(g.user.store_id)
            if store and store.google_token_json:
                try:
                    token_data = json.loads(store.google_token_json)
                    credentials = Credentials(
                        token=token_data['token'],
                        refresh_token=token_data.get('refresh_token'),
                        token_uri=token_data['token_uri'],
                        client_id=token_data['client_id'],
                        client_secret=token_data['client_secret'],
                        scopes=SCOPES
                    )
                    service = build('calendar', 'v3', credentials=credentials)
                    event = {
                        'summary': f"{selected_dog.name} ({selected_dog.owner.name}) Appointment",
                        'description': notes or '',
                        'start': {'dateTime': utc_dt.isoformat(), 'timeZone': 'UTC'},
                        'end': {'dateTime': (utc_dt + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'UTC'},
                    }
                    if appt.google_event_id:
                        # Update existing event
                        service.events().update(calendarId='primary', eventId=appt.google_event_id, body=event).execute()
                    else:
                        # Create new event if missing
                        created_event = service.events().insert(calendarId='primary', body=event).execute()
                        appt.google_event_id = created_event.get('id')
                    db.session.commit()
                    flash("Appointment synced to Google Calendar.", "success")
                except Exception as e:
                    current_app.logger.error(f"Google Calendar sync failed: {e}", exc_info=True)
                    flash("Appointment updated, but failed to sync with Google Calendar.", "warning")
            else:
                flash("Appointment updated, but Google Calendar is not connected for this store.", "info")
            
            return redirect(url_for('appointments.calendar_view'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing appt {appointment_id}: {e}", exc_info=True)
            flash("Error editing appointment.", "danger")
            form_data = request.form.to_dict()
            form_data.update({'id': appointment_id, 'dog': appt.dog, 'groomer': appt.groomer})
            return render_template('edit_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=form_data, appointment_id=appointment_id), 500
    
    local_dt_form = appt.appointment_datetime.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
    form_data = {
        'id': appt.id, 
        'dog_id': appt.dog_id, 
        'appointment_date': local_dt_form.strftime('%Y-%m-%d'), 
        'appointment_time': local_dt_form.strftime('%H:%M'), 
        'services_text': appt.requested_services_text, 
        'notes': appt.notes, 
        'status': appt.status, 
        'groomer_id': appt.groomer_id, 
        'dog': appt.dog, 
        'groomer': appt.groomer
    }
    log_activity("Viewed Edit Appointment page", details=f"Appt ID: {appointment_id}")
    return render_template('edit_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=form_data, appointment_id=appointment_id)

@appointments_bp.route('/appointment/<int:appointment_id>/delete', methods=['POST'])
def delete_appointment(appointment_id):
    """
    Handles deleting an appointment.
    Ensures that only appointments from the current store can be deleted.
    """
    store_id = session.get('store_id')  # Get store_id from session

    # Fetch the appointment, ensuring it belongs to the current store
    appt = Appointment.query.options(db.joinedload(Appointment.dog)).filter_by(
        store_id=store_id  # Filter appointment by the current store
    ).get_or_404(appointment_id)
    
    dog_name = appt.dog.name
    local_time = appt.appointment_datetime.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
    time_str = local_time.strftime('%Y-%m-%d %I:%M %p %Z')
    
    try:
        db.session.delete(appt)
        db.session.commit()
        log_activity("Deleted Local Appt", details=f"Appt ID: {appointment_id}, Dog: {dog_name}")
        flash(f"Appt for {dog_name} on {time_str} deleted!", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting appt {appointment_id}: {e}", exc_info=True)
        flash("Error deleting appointment.", "danger")
    
    return redirect(url_for('appointments.calendar_view'))

@appointments_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    """
    Handles the checkout process for appointments.
    (Placeholder - further implementation needed to filter data by store)
    """
    # TODO: Ensure that any data displayed or processed here is also filtered by store_id
    # For example, if displaying a list of appointments for checkout, filter them:
    # appointments_for_checkout = Appointment.query.filter_by(store_id=session.get('store_id'), status='Scheduled').all()
    # And ensure any updates/creations also respect the store_id
    return render_template('checkout.html')
