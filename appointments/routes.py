from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify, current_app, session
from models import Appointment, Dog, Owner, User, ActivityLog, Store, Service
from appointments.details_needed_utils import appointment_needs_details
from extensions import db
from sqlalchemy import or_
from functools import wraps
import datetime
from datetime import timezone
from dateutil import tz, parser as dateutil_parser
from utils import allowed_file # Keep allowed_file from utils
from utils import log_activity   # IMPORT log_activity from utils.py
from utils import subscription_required  # Import subscription_required decorator
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json
import re
import os
import base64
from email.mime.text import MIMEText
from notifications.email_utils import send_appointment_confirmation_email, send_appointment_edited_email, send_appointment_cancelled_email
import pytz

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


@appointments_bp.route('/calendar')
@subscription_required
def calendar_view():
    """
    Displays the calendar view of appointments for the current store.
    Shows the Google Calendar for the current store if connected.
    """
    if 'store_id' not in session:
        return redirect(url_for('auth.login'))
        
    store_id = session['store_id']
    current_app.logger.info(f"Fetching appointments for store_id: {store_id}")

    # Get store and timezone
    store = Store.query.get(store_id)
    store_timezone_name = getattr(store, 'timezone', None) or 'America/New_York'
    try:
        store_timezone = tz.gettz(store_timezone_name)
        if store_timezone is None:
            raise Exception(f"Invalid timezone: {store_timezone_name}")
    except Exception as e:
        current_app.logger.error(f"Error loading timezone '{store_timezone_name}': {str(e)}. Falling back to America/New_York.")
        store_timezone = tz.gettz('America/New_York')
    
    # Sync Google Calendar events but don't let errors break the calendar view
    try:
        from management.routes import sync_google_calendar_for_store
        store = Store.query.get(store_id)
        if store and store.google_token_json and store.google_calendar_id:
            current_app.logger.info("Starting Google Calendar sync...")
            sync_google_calendar_for_store(store, g.user)
            current_app.logger.info("Google Calendar sync completed")
    except Exception as e:
        current_app.logger.error(f"Error syncing Google Calendar: {str(e)}", exc_info=True)
    
    # Get all appointments for the store with all statuses
    current_app.logger.info("Querying local appointments...")
    local_appointments = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter(
        Appointment.store_id == store_id,
        Appointment.status.in_(['Scheduled', 'Completed', 'Cancelled', 'No Show'])
    ).order_by(Appointment.appointment_datetime.asc()).all()
    
    current_app.logger.info(f"Retrieved {len(local_appointments)} appointments")
    for i, appt in enumerate(local_appointments, 1):
        # Ensure details_needed is always up to date
        appt.details_needed = appointment_needs_details(appt.dog, appt.groomer, appt.requested_services_text)
        # Convert appointment time to store timezone for display
        if appt.appointment_datetime.tzinfo is None:
            appt.local_time = appt.appointment_datetime.replace(tzinfo=timezone.utc).astimezone(store_timezone)
        else:
            appt.local_time = appt.appointment_datetime.astimezone(store_timezone)
        current_app.logger.info(
            f"Appt {i}: ID={appt.id}, Status={appt.status}, "
            f"Dog={getattr(appt.dog, 'name', 'None')} (ID: {getattr(appt, 'dog_id', 'None')}), "
            f"Groomer={getattr(appt.groomer, 'username', 'None')} (ID: {getattr(appt, 'groomer_id', 'None')}), "
            f"Time={appt.local_time}, "
            f"GoogleEventID={getattr(appt, 'google_event_id', 'None')}, "
            f"DetailsNeeded={getattr(appt, 'details_needed', 'False')}"
        )
    
    # Format appointments for FullCalendar
    events = []
    for appt in local_appointments:
        if not appt.dog:
            current_app.logger.warning(f"Skipping appointment {appt.id} - no dog associated")
            continue
            
        try:
            # Use local_time for event start (already in store timezone)
            event = {
                'id': appt.id,
                'title': f"{appt.dog.name} - {appt.requested_services_text or 'Appointment'}",
                'start': appt.local_time.isoformat(),
                'status': appt.status,
                'dog_name': appt.dog.name,
                'dog_id': appt.dog.id,
                'owner_name': appt.dog.owner.name if appt.dog.owner else 'Unknown Owner',
                'owner_id': appt.dog.owner.id if appt.dog.owner else None,
                'services': appt.requested_services_text or '',
                'notes': appt.notes or '',
                'groomer': appt.groomer.username if appt.groomer else 'Unassigned',
                'groomer_id': appt.groomer.id if appt.groomer else None,
                'details_needed': appt.details_needed,
                'editable': True,
                'google_event_id': appt.google_event_id or ''
            }
            
            # Set event color based on status
            if appt.status == 'Completed':
                event['color'] = '#28a745'  # Green
            elif appt.status == 'Cancelled':
                event['color'] = '#dc3545'  # Red
                event['editable'] = False
            elif appt.status == 'No Show':
                event['color'] = '#ffc107'  # Yellow
            elif appt.details_needed:
                event['color'] = '#fd7e14'  # Orange
                
            events.append(event)
        except Exception as e:
            current_app.logger.error(f"Error formatting appointment {getattr(appt, 'id', 'unknown')}: {str(e)}", exc_info=True)
    
    current_app.logger.info(f"Successfully formatted {len(events)} events for calendar")
    # Limit to first 5 scheduled appointments for the calendar page preview
    local_appointments_display = [a for a in local_appointments if a.status == 'Scheduled'][:5]
    # Determine Google Calendar embed URL and connection status
    pawfection_calendar_embed_url = None
    is_google_calendar_connected = False
    # store is already loaded above
    if store and store.google_calendar_id:
        pawfection_calendar_embed_url = (
            f"https://calendar.google.com/calendar/embed?src={store.google_calendar_id}&ctz={store_timezone_name.replace('/', '%2F')}&mode=AGENDA&title=Dog%20Schedule"
        )
        is_google_calendar_connected = True

    return render_template(
        'calendar.html',
        local_appointments=local_appointments_display,
        pawfection_calendar_embed_url=pawfection_calendar_embed_url,
        is_google_calendar_connected=is_google_calendar_connected,
        events=json.dumps(events),
        STORE_TIMEZONE=store_timezone,
        tz=tz
    )


@appointments_bp.route('/api/appointments')
@subscription_required
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
        # Defensive: reload relationships in case of stale data
        db.session.refresh(appt)
        dog_name = appt.dog.name if appt.dog else 'Unknown Dog'
        owner_name = appt.dog.owner.name if appt.dog and appt.dog.owner else 'Unknown Owner'
        groomer_name = appt.groomer.username if appt.groomer else "Unassigned"
        title = f"{dog_name} ({owner_name})"
        if appt.groomer: title += f" - {groomer_name}"
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
            "dog_name": dog_name, 
            "owner_name": owner_name, 
            "groomer_name": groomer_name,
            "status": appt.status, 
            "notes": appt.notes, 
            "services": appt.requested_services_text,
            "url": url_for('appointments.edit_appointment', appointment_id=appt.id), 
            "color": event_color,
            "borderColor": event_color,
            "needs_review": appt.details_needed
        })
    return jsonify(events)

@appointments_bp.route('/add_appointment', methods=['GET', 'POST'])
@subscription_required
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
        selected_dog = db.session.get(Dog, dog_id) if dog_id else None
        
        if not selected_dog or selected_dog.store_id != store_id:
            errors['dog_invalid'] = "Dog not found or does not belong to this store."
        
        groomer_id = int(groomer_id_str) if groomer_id_str and groomer_id_str.isdigit() else None
        selected_groomer = db.session.get(User, groomer_id) if groomer_id else None
        if groomer_id and (not selected_groomer or selected_groomer.store_id != store_id):
            errors['groomer_invalid'] = "Groomer not found or does not belong to this store."

        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            return render_template('add_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=request.form.to_dict()), 400
        
        # Determine if details are needed
        details_needed = appointment_needs_details(selected_dog, selected_groomer, services_text)
        new_appt = Appointment(
            dog_id=selected_dog.id, 
            appointment_datetime=utc_dt, 
            requested_services_text=services_text or None, 
            notes=notes or None, 
            status='Scheduled', 
            created_by_user_id=g.user.id, 
            groomer_id=groomer_id,
            store_id=store_id,
            details_needed=details_needed
        )
        
        try:
            db.session.add(new_appt)
            db.session.commit()
            # Refresh with joined relationships
            new_appt = Appointment.query.options(db.joinedload(Appointment.dog).joinedload(Dog.owner), db.joinedload(Appointment.groomer)).get(new_appt.id)
            log_activity("Added Local Appt", details=f"Dog: {selected_dog.name}, Time: {local_dt_for_log.strftime('%Y-%m-%d %I:%M %p %Z') if local_dt_for_log else 'N/A'}")
            
            # --- Google Calendar Sync ---
            store = db.session.get(Store, g.user.store_id)
            if store and store.google_token_json:
                try:
                    token_data = json.loads(store.google_token_json)
                    credentials = Credentials(
                        token=token_data.get('token') or token_data.get('access_token'),
                        refresh_token=token_data.get('refresh_token'),
                        token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                        client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
                        client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
                        scopes=SCOPES
                    )
                    service = build('calendar', 'v3', credentials=credentials)
                    event = {
                        'summary': f"[{status.upper() if 'status' in locals() else 'SCHEDULED'}] ({selected_dog.name}) Appointment",
                        'description': f"Owner: {selected_dog.owner.name if selected_dog and selected_dog.owner else ''}\n" +
                                       f"Groomer: {selected_groomer.username if selected_groomer else ''}\n" +
                                       f"Services: {services_text if services_text else ''}\n" +
                                       f"Notes: {notes if notes else ''}\n" +
                                       f"Status: {status if 'status' in locals() else 'Scheduled'}",
                        'start': {'dateTime': utc_dt.isoformat(), 'timeZone': 'UTC'},
                        'end': {'dateTime': (utc_dt + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'UTC'},
                    }
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
            notification_settings_path = os.path.join(current_app.root_path, 'notification_settings.json')
            try:
                with open(notification_settings_path, 'r') as f:
                    notification_settings = json.load(f)
            except Exception as e:
                notification_settings = {}
                current_app.logger.error(f"Could not load notification settings: {e}")
            if notification_settings.get('send_confirmation_email', False):
                owner = selected_dog.owner
                groomer = selected_groomer
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
@subscription_required
def edit_appointment(appointment_id):
    """
    Handles editing an existing appointment.
    Ensures that only appointments, dogs, and groomers from the current store are accessible.
    """
    current_app.logger.info(f"Starting edit_appointment for appointment_id: {appointment_id}")
    store_id = session.get('store_id')
    current_app.logger.info(f"Current store_id from session: {store_id}")
    
    appt = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter_by(
        id=appointment_id,
        store_id=store_id
    ).first()
    
    if not appt:
        current_app.logger.error(f"Appointment {appointment_id} not found or not accessible for store {store_id}")
        from flask import abort
        abort(404)

    dogs = Dog.query.options(db.joinedload(Dog.owner)).filter_by(store_id=store_id).order_by(Dog.name).all()
    groomers_for_dropdown = User.query.filter_by(is_groomer=True, store_id=store_id).order_by(User.username).all()

    if request.method == 'POST':
        current_app.logger.info("Processing POST request to edit appointment")
        form_data = request.form.to_dict()
        current_app.logger.info(f"Form data received: {form_data}")
        
        dog_id_str = request.form.get('dog_id')
        date_str = request.form.get('appointment_date')
        time_str = request.form.get('appointment_time')
        services_text = request.form.get('services_text', '').strip()
        notes = request.form.get('notes', '').strip()
        status = request.form.get('status', 'Scheduled').strip()
        groomer_id_str = request.form.get('groomer_id')
        
        current_app.logger.info(f"Processing appointment update - Dog: {dog_id_str}, Date: {date_str}, Time: {time_str}, Status: {status}")
        
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
        selected_dog = db.session.get(Dog, dog_id) if dog_id else None
        
        if not selected_dog or selected_dog.store_id != store_id:
            errors['dog_invalid'] = "Dog not found or does not belong to this store."

        groomer_id = int(groomer_id_str) if groomer_id_str and groomer_id_str.isdigit() else None
        selected_groomer = db.session.get(User, groomer_id) if groomer_id else None
        if groomer_id and (not selected_groomer or selected_groomer.store_id != store_id):
            errors['groomer_invalid'] = "Groomer not found or does not belong to this store."

        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict()
            form_data.update({'id': appointment_id, 'dog': appt.dog, 'groomer': appt.groomer})
            return render_template('edit_appointment.html', dogs=dogs, users=groomers_for_dropdown, appointment_data=form_data, appointment_id=appointment_id), 400
        
        # Update the appointment object with form data
        if selected_dog:
            appt.dog_id = selected_dog.id
            current_app.logger.info(f"Updated dog_id to {selected_dog.id}")
            
        if groomer_id is not None:
            appt.groomer_id = groomer_id
            current_app.logger.info(f"Updated groomer_id to {groomer_id}")
            
        if utc_dt:
            appt.appointment_datetime = utc_dt
            current_app.logger.info(f"Updated appointment_datetime to {utc_dt}")
            
        appt.requested_services_text = services_text or None
        appt.notes = notes or None
        appt.status = status
        current_app.logger.info(f"Updated services: {services_text}, notes: {bool(notes)}, status: {status}")

        # Use the updated dog and groomer objects for details_needed
        current_dog = selected_dog if selected_dog else db.session.get(Dog, appt.dog_id)
        current_groomer = selected_groomer if selected_groomer else db.session.get(User, appt.groomer_id) if appt.groomer_id else None
        appt.details_needed = appointment_needs_details(current_dog, current_groomer, services_text)
        current_app.logger.info(f"Updated details_needed to {appt.details_needed}")
        
        try:
            # Add the appointment to the session if it's not already in it
            if appt not in db.session:
                db.session.add(appt)
            
            # Log the state before commit
            current_app.logger.info(f"Before commit - Appt ID: {appt.id}, Status: {appt.status}, "
                                  f"Dog: {appt.dog_id}, Groomer: {appt.groomer_id}, "
                                  f"Time: {appt.appointment_datetime}, "
                                  f"Services: {appt.requested_services_text}, "
                                  f"Notes: {appt.notes}")
            
            # Save changes to the database
            db.session.commit()
            current_app.logger.info("Successfully saved appointment changes to database")
            
            # Verify the changes were saved
            db.session.refresh(appt)
            current_app.logger.info(f"After commit - Appt ID: {appt.id}, Status: {appt.status}, "
                                  f"Dog: {appt.dog_id}, Groomer: {appt.groomer_id}, "
                                  f"Time: {appt.appointment_datetime}, "
                                  f"Services: {appt.requested_services_text}, "
                                  f"Notes: {appt.notes}")
            
            # Log the changes
            log_message = f"Edited Local Appt - ID: {appointment_id}, Status: {status}, " \
                        f"Time: {local_dt_for_log.strftime('%Y-%m-%d %I:%M %p %Z') if local_dt_for_log else 'N/A'}, " \
                        f"Dog: {selected_dog.name if selected_dog else 'None'}, " \
                        f"Groomer: {selected_groomer.username if selected_groomer else 'Unassigned'}"
            
            current_app.logger.info(log_message)
            log_activity("Edited Local Appt", log_message)
            
            # --- Google Calendar Sync ---
            google_sync_success = True
            store = db.session.get(Store, store_id)
            if store and store.google_token_json:
                try:
                    # Create a new session for Google Calendar operations
                    with db.session.no_autoflush:
                        token_data = json.loads(store.google_token_json)
                        credentials = Credentials(
                            token=token_data.get('token') or token_data.get('access_token'),
                            refresh_token=token_data.get('refresh_token'),
                            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                            client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
                            client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
                            scopes=SCOPES
                        )
                        service = build('calendar', 'v3', credentials=credentials)
                        event = {
                            'summary': f"[{status.upper() if 'status' in locals() else 'SCHEDULED'}] ({selected_dog.name}) Appointment",
                            'description': f"Owner: {selected_dog.owner.name if selected_dog and selected_dog.owner else ''}\n" +
                                           f"Groomer: {selected_groomer.username if selected_groomer else ''}\n" +
                                           f"Services: {services_text if services_text else ''}\n" +
                                           f"Notes: {notes if notes else ''}\n" +
                                           f"Status: {status}",
                            'start': {'dateTime': utc_dt.isoformat(), 'timeZone': 'UTC'},
                            'end': {'dateTime': (utc_dt + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'UTC'},
                        }
                        calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'
                        
                        # Execute Google Calendar operation in a separate try-except
                        try:
                            if appt.google_event_id:
                                service.events().update(
                                    calendarId=calendar_id, 
                                    eventId=appt.google_event_id, 
                                    body=event
                                ).execute()
                            else:
                                created_event = service.events().insert(
                                    calendarId=calendar_id, 
                                    body=event
                                ).execute()
                                # Update the Google event ID in a separate transaction
                                try:
                                    appt.google_event_id = created_event.get('id')
                                    db.session.commit()
                                except Exception as e:
                                    current_app.logger.error(f"Failed to update Google event ID: {e}", exc_info=True)
                                    google_sync_success = False
                                    
                        except Exception as e:
                            current_app.logger.error(f"Google Calendar API error: {e}", exc_info=True)
                            google_sync_success = False
                            
                except Exception as e:
                    current_app.logger.error(f"Google Calendar setup failed: {e}", exc_info=True)
                    google_sync_success = False
                    
            # Show appropriate flash message based on sync status
            if store and store.google_token_json:
                if google_sync_success:
                    flash("Appointment updated and synced to Google Calendar.", "success")
                else:
                    flash("Appointment updated, but there was an issue syncing with Google Calendar.", "warning")
            else:
                flash("Appointment updated. Google Calendar is not connected for this store.", "info")
                
            # --- Send Edited Email if enabled ---
            notification_settings_path = os.path.join(current_app.root_path, 'notification_settings.json')
            try:
                with open(notification_settings_path, 'r') as f:
                    notification_settings = json.load(f)
            except Exception as e:
                notification_settings = {}
                current_app.logger.error(f"Could not load notification settings: {e}")
            if notification_settings.get('send_confirmation_email', False):
                owner = selected_dog.owner
                groomer = selected_groomer
                send_appointment_edited_email(store, owner, selected_dog, appt, groomer=groomer, services_text=services_text)
            return redirect(url_for('appointments.calendar_view'))
            
        except Exception as e:
            db.session.rollback()
            error_msg = f"Error editing appointment {appointment_id}: {str(e)}"
            current_app.logger.error(error_msg, exc_info=True)
            
            # Log the full traceback
            import traceback
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            
            flash("Error editing appointment. Please check the logs for more details.", "danger")
            form_data = request.form.to_dict()
            form_data.update({'id': appointment_id, 'dog': appt.dog, 'groomer': appt.groomer})
            return render_template('edit_appointment.html', 
                               dogs=dogs, 
                               users=groomers_for_dropdown, 
                               appointment_data=form_data, 
                               appointment_id=appointment_id), 500

        # Log the changes
        log_message = f"Edited Local Appt - ID: {appointment_id}, Status: {status}, " \
                    f"Time: {local_dt_for_log.strftime('%Y-%m-%d %I:%M %p %Z') if local_dt_for_log else 'N/A'}, " \
                    f"Dog: {selected_dog.name if selected_dog else 'None'}, " \
                    f"Groomer: {selected_groomer.username if selected_groomer else 'Unassigned'}"
        
        current_app.logger.info(log_message)
        log_activity("Edited Local Appt", log_message)
        
        # --- Google Calendar Sync ---
        google_sync_success = True
        if store and store.google_token_json:
            try:
                # Create a new session for Google Calendar operations
                with db.session.no_autoflush:
                    token_data = json.loads(store.google_token_json)
                    credentials = Credentials(
                        token=token_data.get('token') or token_data.get('access_token'),
                        refresh_token=token_data.get('refresh_token'),
                        token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                        client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
                        client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
                        scopes=SCOPES
                    )
                    service = build('calendar', 'v3', credentials=credentials)
                    event = {
                        'summary': f"[{status.upper() if 'status' in locals() else 'SCHEDULED'}] ({selected_dog.name}) Appointment",
                        'description': f"Owner: {selected_dog.owner.name if selected_dog and selected_dog.owner else ''}\n" +
                                       f"Groomer: {selected_groomer.username if selected_groomer else ''}\n" +
                                       f"Services: {services_text if services_text else ''}\n" +
                                       f"Notes: {notes if notes else ''}\n" +
                                       f"Status: {status}",
                        'start': {'dateTime': utc_dt.isoformat(), 'timeZone': 'UTC'},
                        'end': {'dateTime': (utc_dt + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'UTC'},
                    }
                    calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'
                    
                    # Execute Google Calendar operation in a separate try-except
                    try:
                        if appt.google_event_id:
                            service.events().update(
                                calendarId=calendar_id, 
                                eventId=appt.google_event_id, 
                                body=event
                            ).execute()
                        else:
                            created_event = service.events().insert(
                                calendarId=calendar_id, 
                                body=event
                            ).execute()
                            # Update the Google event ID in a separate transaction
                            try:
                                appt.google_event_id = created_event.get('id')
                                db.session.commit()
                            except Exception as e:
                                current_app.logger.error(f"Failed to update Google event ID: {e}", exc_info=True)
                                google_sync_success = False
                                
                    except Exception as e:
                        current_app.logger.error(f"Google Calendar API error: {e}", exc_info=True)
                        google_sync_success = False
                        
            except Exception as e:
                current_app.logger.error(f"Google Calendar setup failed: {e}", exc_info=True)
                google_sync_success = False
                
        try:
            # Show appropriate flash message based on sync status
            if store and store.google_token_json:
                if google_sync_success:
                    flash("Appointment updated and synced to Google Calendar.", "success")
                else:
                    flash("Appointment updated, but there was an issue syncing with Google Calendar.", "warning")
            else:
                flash("Appointment updated. Google Calendar is not connected for this store.", "info")
                
            # --- Send Edited Email if enabled ---
            notification_settings_path = os.path.join(current_app.root_path, 'notification_settings.json')
            try:
                with open(notification_settings_path, 'r') as f:
                    notification_settings = json.load(f)
            except Exception as e:
                notification_settings = {}
                current_app.logger.error(f"Could not load notification settings: {e}")
            if notification_settings.get('send_confirmation_email', False):
                owner = selected_dog.owner
                groomer = selected_groomer
                send_appointment_edited_email(store, owner, selected_dog, appt, groomer=groomer, services_text=services_text)
            return redirect(url_for('appointments.calendar_view'))
            
        except Exception as e:
            db.session.rollback()
            error_msg = f"Error editing appointment {appointment_id}: {str(e)}"
            current_app.logger.error(error_msg, exc_info=True)
            
            # Log the full traceback
            import traceback
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            
            flash("Error editing appointment. Please check the logs for more details.", "danger")
            form_data = request.form.to_dict()
            form_data.update({'id': appointment_id, 'dog': appt.dog, 'groomer': appt.groomer})
            return render_template('edit_appointment.html', 
                               dogs=dogs, 
                               users=groomers_for_dropdown, 
                               appointment_data=form_data, 
                               appointment_id=appointment_id), 500
    
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
@subscription_required
def delete_appointment(appointment_id):
    """
    Handles deleting an appointment.
    Ensures that only appointments from the current store can be deleted.
    Provides a choice: delete from both app and Google Calendar, or just mark as Cancelled (and update Google Calendar event status).
    """
    store_id = session.get('store_id')
    appt = Appointment.query.options(db.joinedload(Appointment.dog)).filter_by(
        id=appointment_id,
        store_id=store_id
    ).first()
    if not appt:
        from flask import abort
        abort(404)
    dog_name = appt.dog.name
    # Use store's timezone for formatting time
    store = db.session.get(Store, store_id)
    store_timezone_name = getattr(store, 'timezone', None) or 'America/New_York'
    store_timezone = tz.gettz(store_timezone_name)
    if appt.appointment_datetime.tzinfo is None:
        local_time = appt.appointment_datetime.replace(tzinfo=timezone.utc).astimezone(store_timezone)
    else:
        local_time = appt.appointment_datetime.astimezone(store_timezone)
    time_str = local_time.strftime('%Y-%m-%d %I:%M %p %Z')

    action = request.form.get('delete_action', 'cancel')
    google_event_id = appt.google_event_id
    store = db.session.get(Store, store_id)
    google_calendar_deleted = False
    google_calendar_cancelled = False
    try:
        if action == 'delete':
            # ... (rest of delete logic is fine)
            if store and store.google_token_json and google_event_id:
                try:
                    # Build credentials and Google Calendar service
                    token_data = json.loads(store.google_token_json)
                    credentials = Credentials(
                        token=token_data.get('token') or token_data.get('access_token'),
                        refresh_token=token_data.get('refresh_token'),
                        token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                        client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
                        client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
                        scopes=SCOPES
                    )
                    service = build('calendar', 'v3', credentials=credentials)
                    calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'

                    # Delete the event from Google Calendar
                    service.events().delete(calendarId=calendar_id, eventId=google_event_id).execute()
                    google_calendar_deleted = True
                except Exception as e:
                    current_app.logger.error(f"Failed to delete Google Calendar event: {e}", exc_info=True)
            db.session.delete(appt)
            db.session.commit()
            log_activity("Deleted Local Appt", details=f"Appt ID: {appointment_id}, Dog: {dog_name}")
            msg = f"Appt for {dog_name} on {time_str} deleted!"
            if google_calendar_deleted:
                msg += " (Google Calendar event deleted)"
            # Send cancellation email to owner
            if appt.dog is not None and appt.dog.owner is not None:
                owner = appt.dog.owner
                groomer = appt.groomer if hasattr(appt, 'groomer') else None
                services_text = appt.requested_services_text
                send_appointment_cancelled_email(store, owner, appt.dog, appt, groomer, services_text)
            else:
                current_app.logger.warning(f"[CANCEL EMAIL] Skipping email: appt.dog or appt.dog.owner missing for appt ID {appointment_id}")
            flash(msg, "success")
        else:
            # Mark as Cancelled in app
            appt.status = 'Cancelled'
            db.session.commit()
            db.session.refresh(appt) # <<< FIX: Refresh the object to get the latest state from the DB.

            # Update Google Calendar event if possible
            if store and store.google_token_json and google_event_id:
                try:
                    # Build credentials and Google Calendar service
                    token_data = json.loads(store.google_token_json)
                    credentials = Credentials(
                        token=token_data.get('token') or token_data.get('access_token'),
                        refresh_token=token_data.get('refresh_token'),
                        token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                        client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
                        client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
                        scopes=SCOPES
                    )
                    service = build('calendar', 'v3', credentials=credentials)
                    calendar_id = store.google_calendar_id if store.google_calendar_id else 'primary'

                    # Mark the event as cancelled in Google Calendar (soft delete so history remains)
                    service.events().patch(
                        calendarId=calendar_id,
                        eventId=google_event_id,
                        body={"status": "cancelled", "summary": f"[CANCELLED] ({appt.dog.name}) Appointment"}
                    ).execute()
                    google_calendar_cancelled = True
                except Exception as e:
                    current_app.logger.error(f"Failed to cancel Google Calendar event: {e}", exc_info=True)
            log_activity("Cancelled Local Appt", details=f"Appt ID: {appointment_id}, Dog: {dog_name}")
            msg = f"Appt for {dog_name} on {time_str} marked as Cancelled."
            if google_calendar_cancelled:
                msg += " (Google Calendar event cancelled)"
            # Send cancellation email to owner
            if appt.dog is not None and appt.dog.owner is not None:
                owner = appt.dog.owner
                groomer = appt.groomer if hasattr(appt, 'groomer') else None
                services_text = appt.requested_services_text
                send_appointment_cancelled_email(store, owner, appt.dog, appt, groomer, services_text)
            else:
                current_app.logger.warning(f"[CANCEL EMAIL] Skipping email: appt.dog or appt.dog.owner missing for appt ID {appointment_id}")
            flash(msg, "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting/cancelling appt {appointment_id}: {e}", exc_info=True)
        flash("Error deleting/cancelling appointment.", "danger")
    return redirect(url_for('appointments.calendar_view'))

# ... (the rest of the file remains the same) ...

@appointments_bp.route('/all_appointments')
@subscription_required
def all_appointments():
    """Overview page: shows first 5 of each status with view-all buttons."""
    store_id = session.get('store_id')
    store = Store.query.get(store_id)
    store_timezone_name = getattr(store, 'timezone', None) or 'America/New_York'
    store_timezone = tz.gettz(store_timezone_name) or tz.gettz('America/New_York')

    def _query(status):
        return Appointment.query.options(
            db.joinedload(Appointment.dog).joinedload(Dog.owner),
            db.joinedload(Appointment.groomer)
        ).filter_by(store_id=store_id, status=status).order_by(Appointment.appointment_datetime.asc()).limit(5).all()

    appointments_by_status = {
        'Scheduled': _query('Scheduled'),
        'Completed': _query('Completed'),
        'Cancelled': _query('Cancelled')
    }
    return render_template('all_appointments.html', appointments_by_status=appointments_by_status, STORE_TIMEZONE=store_timezone, tz=tz)


@appointments_bp.route('/appointments/view/<status>')
@subscription_required
def view_appointments_by_status(status):
    """Show all appointments for a specific status with optional search."""
    allowed_statuses = {'scheduled': 'Scheduled', 'completed': 'Completed', 'cancelled': 'Cancelled'}
    status_key = status.lower()
    if status_key not in allowed_statuses:
        flash('Invalid status specified.', 'danger')
        return redirect(url_for('appointments.all_appointments'))

    proper_status = allowed_statuses[status_key]
    store_id = session.get('store_id')
    search_query = request.args.get('q', '').strip()

    query = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter_by(store_id=store_id, status=proper_status)

    if search_query:
        like_str = f"%{search_query}%"
        query = query.join(Dog).join(Owner).filter(
            or_(Dog.name.ilike(like_str), Owner.name.ilike(like_str))
        )

    appointments = query.order_by(Appointment.appointment_datetime.asc()).all()
    store = Store.query.get(store_id)
    store_timezone_name = getattr(store, 'timezone', None) or 'America/New_York'
    store_timezone = tz.gettz(store_timezone_name) or tz.gettz('America/New_York')

    return render_template('appointments_by_status.html', appointments=appointments, status=proper_status, search_query=search_query, STORE_TIMEZONE=store_timezone, tz=tz)


# Register the Google Calendar webhook blueprint
from appointments.google_calendar_webhook import webhook_bp as google_calendar_webhook_bp


@appointments_bp.route('/checkout', methods=['GET', 'POST'])
@subscription_required
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

    all_items = Service.query.filter_by(store_id=store_id).order_by(Service.item_type, Service.name).all()
    all_services = [item for item in all_items if item.item_type == 'service']
    all_fees = [item for item in all_items if item.item_type == 'fee']

    selected_appointment_id = None
    selected_item_ids = []
    calculated_data = None

    if request.method == 'POST':
        action = request.form.get('action')
        selected_appointment_id = request.form.get('appointment_id', type=int)
        service_ids = request.form.getlist('service_ids')
        fee_ids = request.form.getlist('fee_ids')
        selected_item_ids = [int(i) for i in service_ids + fee_ids if i.isdigit()]

        appointment = None
        for appt in scheduled_appointments:
            if appt.id == selected_appointment_id:
                appointment = appt
                break

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
        total = subtotal

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
                appointment.status = 'Completed'
                appointment.checkout_total_amount = total
                db.session.commit()

                store = db.session.get(Store, g.user.store_id)
                if store and store.google_token_json and appointment.google_event_id:
                    try:
                        try:
                            token_info = json.loads(store.google_token_json)
                            creds = Credentials.from_authorized_user_info(token_info, SCOPES)
                            service = build('calendar', 'v3', credentials=creds)

                            # Fetch current event
                            event = service.events().get(calendarId=store.google_calendar_id, eventId=appointment.google_event_id).execute()
                            # Prepend COMPLETED to title if not already
                            summary = event.get('summary', '')
                            if not summary.lower().startswith('completed'):
                                event['summary'] = f"COMPLETED - {summary}"

                            # Update description with status marker
                            desc = event.get('description', '') or ''
                            if 'Status: Completed' not in desc:
                                desc = desc + ("\n" if desc else "") + "Status: Completed"
                            event['description'] = desc

                            updated_event = service.events().update(calendarId=store.google_calendar_id, eventId=appointment.google_event_id, body=event).execute()
                            current_app.logger.info(f"Google Calendar event updated to completed for appointment {appointment.id}: {updated_event.get('id')}")
                        except Exception as gc_e:
                            current_app.logger.error(f"Failed to mark Google Calendar event completed: {gc_e}", exc_info=True)
                            flash("Appointment completed, but failed to update Google Calendar event.", "warning")
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
@subscription_required
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

@appointments_bp.route('/appointments/needs_review')
@subscription_required
def appointments_needs_review():
    """
    Lists all appointments that have details_needed=True for the current store.
    """
    if not hasattr(g, 'user') or not g.user:
        flash("You must be logged in to view this page.", "danger")
        return redirect(url_for('auth.login'))
    store_id = g.user.store_id
    needs_review_appts = Appointment.query.filter_by(store_id=store_id, details_needed=True).order_by(Appointment.appointment_datetime.desc()).all()
    return render_template('appointments_needs_review.html', appointments=needs_review_appts)

@appointments_bp.route('/appointments/appointments_needing_details')
@subscription_required
def appointments_needing_details():
    """
    Lists all scheduled appointments that have details_needed=True for the current store.
    """
    if not hasattr(g, 'user') or not g.user:
        flash("You must be logged in to view this page.", "danger")
        return redirect(url_for('auth.login'))
    store_id = g.user.store_id
    appointments = Appointment.query.options(
        db.joinedload(Appointment.dog).joinedload(Dog.owner),
        db.joinedload(Appointment.groomer)
    ).filter(
        Appointment.store_id == store_id,
        Appointment.status == 'Scheduled',
        Appointment.details_needed == True
    ).order_by(Appointment.appointment_datetime.asc()).all()
    return render_template('appointments_needing_details.html', appointments=appointments)
