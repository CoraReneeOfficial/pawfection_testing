from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify, current_app, session
from models import Appointment, Dog, Owner, User, ActivityLog, Store
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
                    summary = event.get('summary', '')
                    description = event.get('description', '')
                    # Parse summary: DogName (OwnerName) [Groomer: GroomerName] Appointment
                    dog_name = 'Unknown Dog'
                    owner_name = 'Unknown Owner'
                    groomer_name = 'Unknown Groomer'
                    summary_match = re.match(r"(.+?) \((.+?)\)(?: \[Groomer: (.+?)\])? Appointment", summary)
                    if summary_match:
                        dog_name = summary_match.group(1).strip()
                        owner_name = summary_match.group(2).strip()
                        if summary_match.group(3):
                            groomer_name = summary_match.group(3).strip()
                    # Parse description for services, notes, status
                    services_text = None
                    notes = None
                    status = 'Scheduled'
                    for line in description.splitlines():
                        if line.strip().lower().startswith('services:'):
                            services_text = line.split(':', 1)[1].strip()
                        elif line.strip().lower().startswith('notes:'):
                            notes = line.split(':', 1)[1].strip()
                        elif line.strip().lower().startswith('status:'):
                            status = line.split(':', 1)[1].strip().capitalize()
                    # Try to find owner (first try full name, then fallback to first name only)
                    owner = Owner.query.filter_by(name=owner_name, store_id=store.id).first()
                    if not owner:
                        # Try to match by first name (case-insensitive), handle single names
                        owner_first = owner_name.split()[0].strip().lower() if owner_name.strip() else None
                        if owner_first:
                            if ' ' in owner_name:
                                # Get all owners for the store and compare first names in Python
                                possible_owners = Owner.query.filter(Owner.store_id == store.id).all()
                                for possible_owner in possible_owners:
                                    db_first = possible_owner.name.split()[0].strip().lower()
                                    if db_first == owner_first:
                                        owner = possible_owner
                                        break
                            else:
                                owner = Owner.query.filter(
                                    Owner.store_id == store.id,
                                    db.func.lower(Owner.name) == owner_first
                                ).first()
                    if not owner:
                        # Check for existing owner with same phone number and store
                        existing_owner = Owner.query.filter_by(phone_number='N/A', store_id=store.id).first()
                        if existing_owner:
                            owner = existing_owner
                        else:
                            # Check for existing owner with same email and store
                            if owner_name != 'Unknown Owner':
                                existing_owner_email = Owner.query.filter_by(email=description, store_id=store.id).first() if description else None
                                if existing_owner_email:
                                    owner = existing_owner_email
                                else:
                                    owner = Owner(name=owner_name, phone_number='N/A', email=description or None, store_id=store.id)
                                    db.session.add(owner)
                                    db.session.flush()
                            else:
                                owner = Owner(name=owner_name, phone_number='N/A', store_id=store.id)
                                db.session.add(owner)
                                db.session.flush()
                    # Try to find dog (first try full name, then fallback to first name only)
                    dog = Dog.query.filter_by(name=dog_name, owner_id=owner.id, store_id=store.id).first()
                    if not dog:
                        # Check for existing dog with same name, owner, and store
                        existing_dog = Dog.query.filter_by(name=dog_name, owner_id=owner.id, store_id=store.id).first()
                        if existing_dog:
                            dog = existing_dog
                        else:
                            dog = Dog(name=dog_name, owner_id=owner.id, store_id=store.id)
                            db.session.add(dog)
                            db.session.flush()
                    # Try to find groomer
                    groomer = None
                    if groomer_name != 'Unknown Groomer':
                        groomer = User.query.filter_by(username=groomer_name, store_id=store.id, is_groomer=True).first()
                    groomer_id = groomer.id if groomer else None
                    # Check for double booking before creating a new appointment
                    appt = Appointment.query.filter_by(google_event_id=google_event_id, store_id=store.id).first()
                    if not appt:
                        # Double booking safeguard: check for same dog, datetime, and store
                        double_booked = Appointment.query.filter_by(dog_id=dog.id, appointment_datetime=start, store_id=store.id).first()
                        if double_booked:
                            appt = double_booked
                        else:
                            try:
                                # --- Flag for missing details ---
                                details_needed = False
                                if (not dog or dog_name == 'Unknown Dog' or not owner or owner_name == 'Unknown Owner' or not groomer or groomer_name == 'Unknown Groomer'):
                                    details_needed = True
                                new_appt = Appointment(
                                    appointment_datetime=start,
                                    status=status,
                                    created_by_user_id=g.user.id if hasattr(g, 'user') and g.user else None,
                                    store_id=store.id,
                                    google_event_id=google_event_id,
                                    notes=notes or summary,
                                    requested_services_text=services_text,
                                    dog_id=dog.id,
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
                        if appt.notes != (notes or summary):
                            appt.notes = notes or summary
                            updated = True
                        if appt.requested_services_text != services_text:
                            appt.requested_services_text = services_text
                            updated = True
                        if appt.dog_id != dog.id:
                            appt.dog_id = dog.id
                            updated = True
                        if appt.groomer_id != groomer_id:
                            appt.groomer_id = groomer_id
                            updated = True
                        if appt.status != status:
                            appt.status = status
                            updated = True
                        # Update details_needed flag if info is missing
                        new_details_needed = (not dog or dog_name == 'Unknown Dog' or not owner or owner_name == 'Unknown Owner' or not groomer or groomer_name == 'Unknown Groomer')
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
            db.session.commit()
            # Refetch the appointment and related objects after commit
            refreshed_appt = Appointment.query.options(
                db.joinedload(Appointment.dog).joinedload(Dog.owner),
                db.joinedload(Appointment.groomer)
            ).get(appt.id)
            updated_dog = refreshed_appt.dog
            updated_groomer = refreshed_appt.groomer
            details_needed_now = (
                not updated_dog or
                not updated_dog.owner or
                (refreshed_appt.groomer_id and not updated_groomer)
            )
            if refreshed_appt.details_needed != details_needed_now:
                refreshed_appt.details_needed = details_needed_now
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
    """
    store_id = session.get('store_id')  # Get store_id from session

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
    """
    store_id = session.get('store_id')
    scheduled_appointments = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter(
        Appointment.status == 'Scheduled',
        Appointment.store_id == store_id
    ).order_by(Appointment.appointment_datetime.asc()).all()
    # TODO: Add logic for POST/calculate/complete as needed
    return render_template('checkout.html', scheduled_appointments=scheduled_appointments)
