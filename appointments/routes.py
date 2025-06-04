from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify, current_app, session
from models import Appointment, Dog, Owner, User, ActivityLog, Store, Service
from extensions import db
from sqlalchemy import or_
from functools import wraps
import datetime
from datetime import timezone
from dateutil import tz, parser as dateutil_parser
from utils import allowed_file # Keep allowed_file from utils
from utils import log_activity   # IMPORT log_activity from utils.py
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json
import re
import os
import base64
from email.mime.text import MIMEText

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
    Also ensures a Google Calendar named 'Pawfection Appointments' exists and stores its ID.
    Syncs Google Calendar events to the Appointment table (basic mapping).
    """
    log_activity("Viewed Calendar page")
    store_id = session.get('store_id')
    store = Store.query.get(store_id)
    local_appointments = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter(
        Appointment.status == 'Scheduled',
        Appointment.store_id == store_id
    ).order_by(Appointment.appointment_datetime.asc()).all()

    # Log all loaded appointments for debugging
    for appt in local_appointments:
        current_app.logger.info(f"[DEBUG] calendar_view loaded: ID={appt.id}, Time={appt.appointment_datetime}, Status={appt.status}, Dog={appt.dog.name if appt.dog else 'None'}, Notes={appt.notes}")

    is_google_calendar_connected = False
    pawfection_calendar_id = None
    pawfection_calendar_embed_url = None
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
            is_google_calendar_connected = True
            # Check if we already have a calendar ID stored
            if not store.google_calendar_id:
                # Search for a calendar named 'Pawfection Appointments'
                calendar_list = service.calendarList().list().execute()
                pawfection_calendar = None
                for cal in calendar_list.get('items', []):
                    if cal.get('summary') == 'Pawfection Appointments':
                        pawfection_calendar = cal
                        break
                if not pawfection_calendar:
                    # Create the calendar
                    calendar_body = {
                        'summary': 'Pawfection Appointments',
                        'timeZone': BUSINESS_TIMEZONE_NAME
                    }
                    pawfection_calendar = service.calendars().insert(body=calendar_body).execute()
                    # Make the calendar public
                    service.acl().insert(
                        calendarId=pawfection_calendar['id'],
                        body={
                            'role': 'reader',
                            'scope': {'type': 'default'}
                        }
                    ).execute()
                # Store the calendar ID
                store.google_calendar_id = pawfection_calendar['id']
                db.session.commit()
            pawfection_calendar_id = store.google_calendar_id
            # Build the embed URL for this calendar
            pawfection_calendar_embed_url = f"https://calendar.google.com/calendar/embed?height=800&wkst=1&ctz={BUSINESS_TIMEZONE_NAME.replace('/', '%2F')}&mode=AGENDA&title=Pawfection%20Appointments&src={pawfection_calendar_id}"

            # --- Google Calendar → Appointments Sync (enhanced, full parsing) ---
            if store.google_calendar_id:
                events = service.events().list(calendarId=store.google_calendar_id).execute().get('items', [])
                google_event_ids = set()
                for event in events:
                    google_event_id = event['id']
                    google_event_ids.add(google_event_id)
                    start = event['start'].get('dateTime') or event['start'].get('date')
                    if not start:
                        continue
                    description = event.get('description', '')
                    # Do NOT use the summary/title for any appointment info
                    # Parse description for all fields: dog, owner, groomer, services, notes, status
                    dog_name = 'Unknown Dog'
                    owner_name = 'Unknown Owner'
                    groomer_name = 'Unknown Groomer'
                    services_text = None
                    notes = None
                    status = 'Scheduled'
                    for line in description.splitlines():
                        if line.strip().lower().startswith('dog:'):
                            dog_name = line.split(':', 1)[1].strip()
                        elif line.strip().lower().startswith('owner:'):
                            owner_name = line.split(':', 1)[1].strip()
                        elif line.strip().lower().startswith('groomer:'):
                            groomer_name = line.split(':', 1)[1].strip()
                        elif line.strip().lower().startswith('services:'):
                            services_text = line.split(':', 1)[1].strip()
                        elif line.strip().lower().startswith('notes:'):
                            notes = line.split(':', 1)[1].strip()
                        elif line.strip().lower().startswith('status:'):
                            status = line.split(':', 1)[1].strip().capitalize()
                    # Try to find owner (first try full name, then fallback to first name only)
                    owner = Owner.query.filter_by(name=owner_name, store_id=store.id).first()
                    if not owner:
                        owner_first = owner_name.split()[0].strip().lower() if owner_name.strip() else None
                        if owner_first:
                            possible_owners = Owner.query.filter(Owner.store_id == store.id).all()
                            for possible_owner in possible_owners:
                                db_first = possible_owner.name.split()[0].strip().lower()
                                if db_first == owner_first:
                                    owner = possible_owner
                                    break
                    # Do NOT create a new owner if not found
                    # Try to find dog (first try full name, then fallback to first name only)
                    dog = None
                    if owner:
                        dog = Dog.query.filter_by(name=dog_name, owner_id=owner.id, store_id=store.id).first()
                        if not dog:
                            dog_first = dog_name.split()[0].strip().lower() if dog_name.strip() else None
                            if dog_first:
                                possible_dogs = Dog.query.filter(Dog.owner_id == owner.id, Dog.store_id == store.id).all()
                                for possible_dog in possible_dogs:
                                    db_first = possible_dog.name.split()[0].strip().lower()
                                    if db_first == dog_first:
                                        dog = possible_dog
                                        break
                    # Do NOT create a new dog if not found
                    # Try to find groomer
                    groomer = None
                    if groomer_name != 'Unknown Groomer':
                        groomer = User.query.filter_by(username=groomer_name, store_id=store.id, is_groomer=True).first()
                    groomer_id = groomer.id if groomer else None
                    # Check for double booking before creating a new appointment
                    appt = Appointment.query.filter_by(google_event_id=google_event_id, store_id=store.id).first()
                    if not appt:
                        # Double booking safeguard: check for same dog, datetime, and store
                        double_booked = None
                        if dog:
                            double_booked = Appointment.query.filter_by(dog_id=dog.id, appointment_datetime=start, store_id=store.id).first()
                        if double_booked:
                            appt = double_booked
                        else:
                            try:
                                # --- Flag for missing details ---
                                details_needed = False
                                if (not dog or not owner or dog_name == 'Unknown Dog' or owner_name == 'Unknown Owner' or not groomer or groomer_name == 'Unknown Groomer'):
                                    details_needed = True
                                new_appt = Appointment(
                                    appointment_datetime=start,
                                    status=status,
                                    created_by_user_id=g.user.id if hasattr(g, 'user') and g.user else None,
                                    store_id=store.id,
                                    google_event_id=google_event_id,
                                    notes=notes or description,
                                    requested_services_text=services_text,
                                    dog_id=dog.id if dog else None,
                                    groomer_id=groomer_id,
                                    details_needed=details_needed
                                )
                                db.session.add(new_appt)
                            except Exception as e:
                                current_app.logger.error(f"Failed to create Appointment from Google event: {e}", exc_info=True)
                    else:
                        # Update existing Appointment if details have changed
                        updated = False
                        if str(appt.appointment_datetime) != str(start):
                            appt.appointment_datetime = start
                            updated = True
                        if appt.notes != (notes or description):
                            appt.notes = notes or description
                            updated = True
                        if appt.requested_services_text != services_text:
                            appt.requested_services_text = services_text
                            updated = True
                        if appt.dog_id != (dog.id if dog else None):
                            appt.dog_id = dog.id if dog else None
                            updated = True
                        if appt.groomer_id != groomer_id:
                            appt.groomer_id = groomer_id
                            updated = True
                        if appt.status != status:
                            appt.status = status
                            updated = True
                        # Update details_needed flag if info is missing
                        new_details_needed = (not dog or not owner or dog_name == 'Unknown Dog' or owner_name == 'Unknown Owner' or not groomer or groomer_name == 'Unknown Groomer')
                        if appt.details_needed != new_details_needed:
                            appt.details_needed = new_details_needed
                            updated = True
                        if updated:
                            try:
                                db.session.add(appt)
                            except Exception as e:
                                current_app.logger.error(f"Failed to update Appointment from Google event: {e}", exc_info=True)
                # Mark appointments as Cancelled if their event was deleted from Google Calendar
                db_appts = Appointment.query.filter_by(store_id=store.id).filter(Appointment.google_event_id.isnot(None)).all()
                for db_appt in db_appts:
                    if db_appt.google_event_id not in google_event_ids and db_appt.status != 'Cancelled':
                        db_appt.status = 'Cancelled'
                        try:
                            db.session.add(db_appt)
                        except Exception as e:
                            current_app.logger.error(f"Failed to mark Appointment as Cancelled: {e}", exc_info=True)
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Failed to commit Google Calendar sync: {e}", exc_info=True)
        except Exception as e:
            current_app.logger.error(f"Google Calendar check/create failed: {e}", exc_info=True)
            is_google_calendar_connected = False
    return render_template('calendar.html',
        local_appointments=local_appointments,
        is_google_calendar_connected=is_google_calendar_connected,
        pawfection_calendar_embed_url=pawfection_calendar_embed_url
    )

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

def send_appointment_confirmation_email(store, owner, dog, appointment, groomer=None, services_text=None):
    """
    Sends an appointment confirmation email to the owner using the store's Gmail API credentials.
    """
    if not owner.email:
        current_app.logger.warning(f"No email for owner {owner.name}, skipping confirmation email.")
        return False
    if not store or not store.google_token_json:
        current_app.logger.warning(f"No Google token for store {getattr(store, 'id', None)}, cannot send email.")
        return False
    try:
        # Load Gmail credentials
        token_data = json.loads(store.google_token_json)
        credentials = Credentials(
            token=token_data['token'],
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data['token_uri'],
            client_id=token_data['client_id'],
            client_secret=token_data['client_secret'],
            scopes=SCOPES
        )
        service = build('gmail', 'v1', credentials=credentials)

        # Prepare email context
        business_name = store.name if hasattr(store, 'name') and store.name else 'Pawfection Grooming'
        BUSINESS_TIMEZONE_NAME = 'America/New_York'
        BUSINESS_TIMEZONE = tz.gettz(BUSINESS_TIMEZONE_NAME)
        appointment_datetime_local = appointment.appointment_datetime.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
        groomer_name = groomer.username if groomer else None
        # Render the email HTML using the template
        html_body = render_template('email/appointment_confirmation.html',
            owner_name=owner.name,
            dog_name=dog.name,
            business_name=business_name,
            appointment_datetime_local=appointment_datetime_local,
            services_text=services_text,
            groomer_name=groomer_name,
            BUSINESS_TIMEZONE_NAME=BUSINESS_TIMEZONE_NAME,
            now=datetime.datetime.now
        )
        subject = f"Appointment Confirmation for {dog.name} at {business_name}"
        message = MIMEText(html_body, 'html')
        message['to'] = owner.email
        message['from'] = token_data.get('sender_email', owner.email) if token_data.get('sender_email') else owner.email
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_message = {'raw': raw}
        service.users().messages().send(userId='me', body=send_message).execute()
        current_app.logger.info(f"Sent appointment confirmation email to {owner.email}")
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send appointment confirmation email: {e}", exc_info=True)
        return False

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
                        'summary': f"({selected_dog.name}) Appointment",
                        'description': f"Owner: {selected_dog.owner.name if selected_dog and selected_dog.owner else ''}\n" +
                                       f"Groomer: {selected_groomer.username if groomer_id and 'selected_groomer' in locals() and selected_groomer else ''}\n" +
                                       f"Services: {services_text if services_text else ''}\n" +
                                       f"Notes: {notes if notes else ''}\n" +
                                       f"Status: {status if 'status' in locals() else 'Scheduled'}",
                        'start': {'dateTime': utc_dt.isoformat(), 'timeZone': 'UTC'},
                        'end': {'dateTime': (utc_dt + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'UTC'},
                    }
                    # Use the correct calendar ID
                    calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'
                    created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
                    new_appt.google_event_id = created_event.get('id')
                    db.session.commit()
                    flash("Appointment synced to Google Calendar.", "success")
                except Exception as e:
                    current_app.logger.error(f"Google Calendar sync failed: {e}", exc_info=True)
                    flash("Appointment saved, but failed to sync with Google Calendar.", "warning")
            else:
                flash("Appointment saved, but Google Calendar is not connected for this store.", "info")
            
            # --- Send Confirmation Email if enabled ---
            # Load notification settings
            notification_settings_path = os.path.join(current_app.root_path, '..', 'notification_settings.json')
            try:
                with open(notification_settings_path, 'r') as f:
                    notification_settings = json.load(f)
            except Exception as e:
                notification_settings = {}
                current_app.logger.error(f"Could not load notification settings: {e}")
            if notification_settings.get('send_confirmation_email', False):
                owner = selected_dog.owner
                groomer = selected_groomer if groomer_id else None
                send_appointment_confirmation_email(store, owner, selected_dog, new_appt, groomer=groomer, services_text=services_text)

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
    current_app.logger.info(f"[DEBUG] (edit_appointment) session['store_id']: {store_id}")
    # Fetch the appointment, ensuring it belongs to the current store
    appt = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter_by(
        id=appointment_id,
        store_id=store_id  # Filter appointment by the current store
    ).first()
    if not appt:
        from flask import abort
        abort(404)

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
            print(f"[DEBUG] Attempting to commit appointment edit for ID {appointment_id}")
            db.session.commit()
            print(f"[DEBUG] Commit successful for appointment edit ID {appointment_id}")
            # After commit, check if the appointment exists and print details
            appt_check = Appointment.query.filter_by(id=appointment_id, store_id=store_id).first()
            if appt_check:
                current_app.logger.info(f"[DEBUG] (edit_appointment) Appointment with ID {appointment_id} and store_id {store_id} exists after edit.")
            else:
                current_app.logger.warning(f"[DEBUG] (edit_appointment) Appointment with ID {appointment_id} and store_id {store_id} NOT FOUND after edit.")
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
                        'summary': f"({selected_dog.name}) Appointment",
                        'description': f"Owner: {selected_dog.owner.name if selected_dog and selected_dog.owner else ''}\n" +
                                       f"Groomer: {selected_groomer.username if groomer_id and 'selected_groomer' in locals() and selected_groomer else ''}\n" +
                                       f"Services: {services_text if services_text else ''}\n" +
                                       f"Notes: {notes if notes else ''}\n" +
                                       f"Status: {status if 'status' in locals() else 'Scheduled'}",
                        'start': {'dateTime': utc_dt.isoformat(), 'timeZone': 'UTC'},
                        'end': {'dateTime': (utc_dt + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'UTC'},
                    }
                    # Use the correct calendar ID
                    calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'
                    if appt.google_event_id:
                        # Update existing event
                        service.events().update(calendarId=calendar_id, eventId=appt.google_event_id, body=event).execute()
                    else:
                        # Create new event if missing
                        created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
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
    Provides a choice: delete from both app and Google Calendar, or just mark as Cancelled (and update Google Calendar event status).
    """
    store_id = session.get('store_id')  # Get store_id from session
    current_app.logger.info(f"[DEBUG] (delete_appointment) session['store_id']: {store_id}")
    # Fetch the appointment, ensuring it belongs to the current store
    appt = Appointment.query.options(db.joinedload(Appointment.dog)).filter_by(
        id=appointment_id,
        store_id=store_id
    ).first()
    if not appt:
        from flask import abort
        abort(404)
    dog_name = appt.dog.name
    local_time = appt.appointment_datetime.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
    time_str = local_time.strftime('%Y-%m-%d %I:%M %p %Z')

    # Determine user choice: delete or cancel
    action = request.form.get('delete_action', 'cancel')  # 'delete' or 'cancel', default to 'cancel'
    google_event_id = appt.google_event_id
    store = Store.query.get(store_id)
    google_calendar_deleted = False
    google_calendar_cancelled = False
    try:
        if action == 'delete':
            # Delete from Google Calendar if possible
            if store and store.google_token_json and google_event_id:
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
                    calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'
                    service.events().delete(calendarId=calendar_id, eventId=google_event_id).execute()
                    google_calendar_deleted = True
                except Exception as e:
                    current_app.logger.error(f"Failed to delete Google Calendar event: {e}", exc_info=True)
            print(f"[DEBUG] Attempting to delete appointment ID {appointment_id}")
            db.session.delete(appt)
            db.session.commit()
            print(f"[DEBUG] Commit successful for delete appointment ID {appointment_id}")
            # After commit, check if the appointment still exists
            appt_check = Appointment.query.filter_by(id=appointment_id, store_id=store_id).first()
            if appt_check:
                current_app.logger.warning(f"[DEBUG] (delete_appointment) Appointment with ID {appointment_id} and store_id {store_id} STILL EXISTS after delete.")
            else:
                current_app.logger.info(f"[DEBUG] (delete_appointment) Appointment with ID {appointment_id} and store_id {store_id} successfully deleted.")
            log_activity("Deleted Local Appt", details=f"Appt ID: {appointment_id}, Dog: {dog_name}")
            msg = f"Appt for {dog_name} on {time_str} deleted!"
            if google_calendar_deleted:
                msg += " (Google Calendar event deleted)"
            flash(msg, "success")
        else:
            # Mark as Cancelled in app and update Google Calendar event if possible
            appt.status = 'Cancelled'
            db.session.commit()
            if store and store.google_token_json and google_event_id:
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
                    calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'
                    event = service.events().get(calendarId=calendar_id, eventId=google_event_id).execute()
                    event['status'] = 'cancelled'
                    service.events().update(calendarId=calendar_id, eventId=google_event_id, body=event).execute()
                    google_calendar_cancelled = True
                except Exception as e:
                    current_app.logger.error(f"Failed to cancel Google Calendar event: {e}", exc_info=True)
            log_activity("Cancelled Local Appt", details=f"Appt ID: {appointment_id}, Dog: {dog_name}")
            msg = f"Appt for {dog_name} on {time_str} marked as Cancelled."
            if google_calendar_cancelled:
                msg += " (Google Calendar event cancelled)"
            flash(msg, "success")
    except Exception as e:
        db.session.rollback()
        print(f"[DEBUG] Exception during delete appointment ID {appointment_id}: {e}")
        current_app.logger.error(f"Error deleting/cancelling appt {appointment_id}: {e}", exc_info=True)
        flash("Error deleting/cancelling appointment.", "danger")
    return redirect(url_for('appointments.calendar_view'))

@appointments_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    """
    Handles the checkout process for appointments.
    """
    store_id = session.get('store_id')
    scheduled_appointments = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter(
        Appointment.status == 'Scheduled',
        Appointment.store_id == store_id
    ).order_by(Appointment.appointment_datetime.asc()).all()

    # Fetch all services and fees for the current store
    all_items = Service.query.filter_by(store_id=store_id).order_by(Service.item_type, Service.name).all()
    all_services = [item for item in all_items if item.item_type == 'service']
    all_fees = [item for item in all_items if item.item_type == 'fee']

    # Defaults for template context
    selected_appointment_id = None
    selected_item_ids = []
    calculated_data = None

    if request.method == 'POST':
        action = request.form.get('action')
        selected_appointment_id = request.form.get('appointment_id', type=int)
        # Get selected service and fee IDs as integers
        service_ids = request.form.getlist('service_ids')
        fee_ids = request.form.getlist('fee_ids')
        selected_item_ids = [int(i) for i in service_ids + fee_ids if i.isdigit()]

        # Find the selected appointment
        appointment = None
        for appt in scheduled_appointments:
            if appt.id == selected_appointment_id:
                appointment = appt
                break

        # Gather selected items
        billed_items = []
        subtotal = 0.0
        for s in all_services:
            if s.id in selected_item_ids:
                billed_items.append(s)
                subtotal += s.base_price
        for f in all_fees:
            if f.id in selected_item_ids:
                billed_items.append(f)
                subtotal += f.base_price
        total = subtotal  # Add tax/discount logic here if needed

        if action == 'calculate_total':
            if appointment:
                calculated_data = {
                    'appointment': appointment,
                    'dog': appointment.dog,
                    'owner': appointment.dog.owner,
                    'billed_items': billed_items,
                    'subtotal': subtotal,
                    'total': total
                }
        elif action == 'complete_checkout':
            if appointment:
                # Mark appointment as completed and save total
                appointment.status = 'Completed'
                appointment.checkout_total_amount = total
                db.session.commit()

                # --- Google Calendar Sync ---
                store = Store.query.get(session.get('store_id'))
                if store and store.google_token_json and appointment.google_event_id:
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
                        # Prepare event update
                        event = {
                            'summary': f"({appointment.dog.name}) Appointment",
                            'description': f"Owner: {appointment.dog.owner.name if appointment.dog and appointment.dog.owner else ''}\n" +
                                           f"Groomer: {appointment.groomer.username if appointment.groomer else ''}\n" +
                                           f"Services: {appointment.requested_services_text if appointment.requested_services_text else ''}\n" +
                                           f"Notes: {appointment.notes if appointment.notes else ''}\n" +
                                           f"Status: Completed",
                            'start': {'dateTime': appointment.appointment_datetime.isoformat(), 'timeZone': 'UTC'},
                            'end': {'dateTime': (appointment.appointment_datetime + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'UTC'},
                        }
                        calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'
                        service.events().update(calendarId=calendar_id, eventId=appointment.google_event_id, body=event).execute()
                        flash("Appointment synced to Google Calendar.", "success")
                    except Exception as e:
                        current_app.logger.error(f"Google Calendar sync failed: {e}", exc_info=True)
                        flash("Appointment completed, but failed to sync with Google Calendar.", "warning")
                else:
                    flash("Appointment completed, but Google Calendar is not connected for this store.", "info")

                calculated_data = {
                    'appointment': appointment,
                    'dog': appointment.dog,
                    'owner': appointment.dog.owner,
                    'billed_items': billed_items,
                    'subtotal': subtotal,
                    'total': total
                }
                flash('Checkout completed and appointment marked as completed.', 'success')
                # Optionally, redirect to a confirmation or dashboard page
                return redirect(url_for('appointments.checkout'))

    return render_template(
        'checkout.html',
        scheduled_appointments=scheduled_appointments,
        all_services=all_services,
        all_fees=all_fees,
        selected_appointment_id=selected_appointment_id,
        selected_item_ids=selected_item_ids,
        calculated_data=calculated_data
    )

@appointments_bp.route('/appointments/debug_list')
def debug_list_appointments():
    """
    Debug endpoint: Returns a plain text list of all appointments in the database.
    """
    appts = Appointment.query.order_by(Appointment.appointment_datetime.asc()).all()
    lines = []
    for appt in appts:
        dog_name = appt.dog.name if appt.dog else 'None'
        owner_name = appt.dog.owner.name if appt.dog and appt.dog.owner else 'None'
        lines.append(f"ID: {appt.id}, Dog: {dog_name}, Owner: {owner_name}, Status: {appt.status}, Details Needed: {appt.details_needed}, Store ID: {appt.store_id}, DateTime: {appt.appointment_datetime}")
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}
