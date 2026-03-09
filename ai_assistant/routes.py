from typing import Union
from flask import Blueprint, request, jsonify, render_template, current_app, session, g
from ai_assistant.feature_flag import is_ai_enabled
from google import genai
from google.genai import types
import ollama
import os
import markdown
import datetime
from datetime import timezone
from functools import wraps
from models import Service, Dog, Owner, Appointment, User, Store, Receipt
from extensions import db
from notifications.email_utils import send_appointment_confirmation_email
from dateutil import tz
import pytz

ai_assistant_bp = Blueprint('ai_assistant', __name__)

def ai_enabled_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_ai_enabled():
            return jsonify({"error": "AI Assistant is currently disabled."}), 403
        return f(*args, **kwargs)
    return decorated_function

@ai_assistant_bp.route('/ai/chat', methods=['POST'])
@ai_enabled_required
def chat():
    # Only allow logged-in users to access the AI
    if not g.user:
        return jsonify({"error": "Authentication required."}), 401
    """
    Handles chat messages from the user and returns a response from Gemini.
    """
    user_message = request.json.get('message')
    history = request.json.get('history', [])
    if not user_message:
        return jsonify({"error": "No message provided."}), 400

    current_app.logger.info(f"[AI Chat Request] Received message: '{user_message}', with history length: {len(history)}")

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"error": "AI configuration error: Missing API Key."}), 500

    try:
        client = genai.Client(api_key=api_key)

        # Construct System Prompt with Context
        store_id = session.get('store_id')
        context_data = ""
        if store_id:
            # Fetch minimal context for better answers (e.g. Service list)
            try:
                services = Service.query.filter_by(store_id=store_id).all()
                service_list = ", ".join([f"{s.name} (${s.base_price})" for s in services])
                context_data += "\nAvailable Services: " + service_list
            except Exception as e:
                current_app.logger.warning("AI Context Error (Services): " + str(e))

            try:
                import datetime
                import pytz
                from datetime import timezone
                store_obj = Store.query.get(store_id)
                store_tz_str = getattr(store_obj, 'timezone', None) or 'America/New_York'
                try:
                    store_tz = pytz.timezone(store_tz_str)
                except pytz.UnknownTimeZoneError:
                    store_tz = pytz.timezone('America/New_York')

                now_utc = datetime.datetime.now(timezone.utc)
                now_local = now_utc.astimezone(store_tz)
                time_str = now_local.strftime('%A, %Y-%m-%d %I:%M %p %Z')
                context_data += "\nCurrent Date and Time: " + time_str
            except Exception as e:
                current_app.logger.warning("AI Context Error (Timezone): " + str(e))

        def get_dogs(name: str = "") -> list[str]:
            """
            Fetches a list of dogs in the store to find their IDs and details. Always use this to look up a dog's ID before performing actions like booking an appointment or editing a dog, unless you already know the exact ID.

            Args:
                name: Optional string. The name of the dog to search for. Leave empty to get a general list.

            Returns:
                A list of strings. Each string contains the dog's ID, Name, Breed, and their Owner's ID. Example: "Dog ID: 1, Name: Fido, Breed: Poodle, Owner ID: 5"
            """
            current_app.logger.info(f"[AI Tool Call] get_dogs called with name='{name}'")
            query = Dog.query.filter_by(store_id=store_id)
            if name:
                query = query.filter(Dog.name.ilike(f"%{name}%"))
            dogs = query.limit(10).all()
            if not dogs:
                current_app.logger.info(f"[AI Tool Call] get_dogs returning 'No dogs found.'")
                return ["No dogs found."]
            result = [f"Dog ID: {d.id}, Name: {d.name}, Breed: {d.breed}, Owner ID: {d.owner_id}" for d in dogs]
            current_app.logger.info(f"[AI Tool Call] get_dogs returning {len(dogs)} dogs.")
            return result

        def get_owners(name: str = "") -> list[str]:
            """
            Fetches a list of owners in the store to find their IDs and contact information. Always use this to look up an owner's ID before editing or deleting them, unless you already know the exact ID.

            Args:
                name: Optional string. The name of the owner to search for. Leave empty to get a general list.

            Returns:
                A list of strings. Each string contains the owner's ID, Name, and Phone Number. Example: "Owner ID: 5, Name: Jane Doe, Phone: 555-1234"
            """
            current_app.logger.info(f"[AI Tool Call] get_owners called with name='{name}'")
            query = Owner.query.filter_by(store_id=store_id)
            if name:
                query = query.filter(Owner.name.ilike(f"%{name}%"))
            owners = query.limit(10).all()
            if not owners:
                current_app.logger.info(f"[AI Tool Call] get_owners returning 'No owners found.'")
                return ["No owners found."]
            result = [f"Owner ID: {o.id}, Name: {o.name}, Phone: {o.phone_number}" for o in owners]
            current_app.logger.info(f"[AI Tool Call] get_owners returning {len(owners)} owners.")
            return result

        def add_appointment(dog_id: Union[int, str], date: str, time: str, groomer_id: Union[int, str], services: list[str], notes: str = "") -> str:
            """
            Books a brand new appointment for a specific dog. You must gather all required information before calling this tool.

            Args:
                dog_id: Required. The integer ID of the dog, OR the dog's name as a string. Using the name is highly encouraged! It will fuzzy match the database.
                date: Required string. The date for the appointment, strictly in YYYY-MM-DD format (e.g., "2024-10-31").
                time: Required string. The time for the appointment, strictly in 24-hour HH:MM format (e.g., "14:30" for 2:30 PM).
                groomer_id: Required. The integer ID of the groomer, OR the groomer's name as a string. Using the name is encouraged!
                services: Required list of strings. A list containing the names or IDs of the services to be performed (e.g., ["Bath", "Nail Trim"]).
                notes: Optional string. Any special instructions or notes for the appointment.

            Returns:
                A string indicating whether the appointment booking was successful or if an error occurred.
            """
            current_app.logger.info(f"[AI Tool Call] add_appointment called with dog_id={dog_id}, groomer_id={groomer_id}, date='{date}', time='{time}', services='{services}', notes='{notes}'")
            try:
                # Handle dog_id as int or string name
                dog = None
                if isinstance(dog_id, int) or (isinstance(dog_id, str) and dog_id.isdigit()):
                    dog = Dog.query.options(db.joinedload(Dog.owner)).filter_by(id=int(dog_id), store_id=store_id).first()
                else:
                    # Try exact match first
                    dogs = Dog.query.options(db.joinedload(Dog.owner)).filter(Dog.name.ilike(dog_id), Dog.store_id == store_id).all()
                    if not dogs:
                        # Fallback to fuzzy match
                        dogs = Dog.query.options(db.joinedload(Dog.owner)).filter(Dog.name.ilike(f"%{dog_id}%"), Dog.store_id == store_id).all()
                    if len(dogs) == 1:
                        dog = dogs[0]
                    elif len(dogs) > 1:
                        # Just take the first one if there are multiple matches to be helpful instead of failing
                        dog = dogs[0]

                if not dog:
                    return f"Error: Dog '{dog_id}' not found. Please ask the user to clarify or provide more details."

                # Handle groomer_id as int or string name
                groomer = None
                if isinstance(groomer_id, int) or (isinstance(groomer_id, str) and groomer_id.isdigit()):
                    groomer = User.query.filter_by(id=int(groomer_id), store_id=store_id, is_groomer=True).first()
                else:
                    # Try exact match first
                    groomers = User.query.filter(User.username.ilike(groomer_id), User.store_id == store_id, User.is_groomer == True).all()
                    if not groomers:
                        # Fallback to fuzzy match
                        groomers = User.query.filter(User.username.ilike(f"%{groomer_id}%"), User.store_id == store_id, User.is_groomer == True).all()
                    if len(groomers) == 1:
                        groomer = groomers[0]
                    elif len(groomers) > 1:
                         groomer = groomers[0]

                if not groomer:
                    return f"Error: Groomer '{groomer_id}' not found. Please ask the user to clarify."

                try:
                    naive_dt = datetime.datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                    store_obj = Store.query.get(store_id)
                    store_tz_str = getattr(store_obj, 'timezone', None) or 'America/New_York'
                    try:
                        store_tz = pytz.timezone(store_tz_str)
                    except pytz.UnknownTimeZoneError:
                        store_tz = pytz.timezone('America/New_York')

                    local_dt = store_tz.localize(naive_dt)
                    appt_datetime = local_dt.astimezone(timezone.utc)
                except ValueError:
                    return "Error: Invalid date/time format. Expected YYYY-MM-DD and HH:MM."

                appt = Appointment(
                    dog_id=dog.id,
                    groomer_id=groomer.id,
                    appointment_datetime=appt_datetime,
                    notes=notes,
                    store_id=store_id,
                    created_by_user_id=g.user.id
                )
                db.session.add(appt)

                # Handle Services
                services_text_list = []
                for s in services:
                    s_str = str(s).strip()
                    if s_str.isdigit():
                        service_obj = Service.query.filter_by(id=int(s_str), store_id=store_id).first()
                    else:
                        service_obj = Service.query.filter(Service.name.ilike(s_str), Service.store_id == store_id).first()

                    if service_obj:
                        services_text_list.append(str(service_obj.id))

                services_text = ','.join(services_text_list)
                appt.requested_services_text = services_text

                db.session.commit()

                # Post-appointment tasks (Sync and Notify)
                try:
                    store_obj = Store.query.get(store_id)

                    # 1. Sync Google Calendar
                    try:
                        from utils import get_google_service
                        if store_obj and store_obj.google_token_json:
                            service = get_google_service('calendar', 'v3', store=store_obj)
                            if service:
                                status_str = 'Scheduled'
                                event = {
                                    'summary': f"[{status_str.upper()}] ({dog.name}) Appointment",
                                    'description': f"Owner: {dog.owner.name if dog and dog.owner else ''}\n" +
                                                   f"Groomer: {groomer.username if groomer else ''}\n" +
                                                   f"Services: {services_text if services_text else ''}\n" +
                                                   f"Notes: {notes if notes else ''}\n" +
                                                   f"Status: {status_str}",
                                    'start': {'dateTime': appt_datetime.isoformat(), 'timeZone': 'UTC'},
                                    'end': {'dateTime': (appt_datetime + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'UTC'},
                                }
                                calendar_id = store_obj.google_calendar_id if store_obj.google_calendar_id else 'primary'
                                created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
                                appt.google_event_id = created_event.get('id')
                                db.session.commit()
                    except Exception as e:
                        current_app.logger.error(f"[AI Tool Call] Google Calendar sync failed: {e}")

                    # Reload appointment with relationships
                    new_appt = Appointment.query.options(
                        db.joinedload(Appointment.dog).joinedload(Dog.owner),
                        db.joinedload(Appointment.groomer)
                    ).filter_by(id=appt.id).first()

                    # 2. Send Notifications (Email/Text) based on settings
                    if dog.owner:
                        import json
                        import os

                        notification_settings_path = os.path.join(current_app.root_path, 'notification_settings.json')
                        try:
                            with open(notification_settings_path, 'r') as f:
                                notification_settings = json.load(f)
                        except Exception as e:
                            notification_settings = {}
                            current_app.logger.error(f"[AI Tool Call] Could not load notification settings: {e}")

                        if notification_settings.get('send_confirmation_email', False):
                            try:
                                from notifications.email_utils import send_appointment_confirmation_email
                                send_appointment_confirmation_email(store_obj, dog.owner, dog, new_appt, groomer=groomer, services_text=services_text)
                            except Exception as e:
                                current_app.logger.error(f"[AI Tool Call] Failed to send email/text notification: {e}")

                except Exception as e:
                    current_app.logger.error(f"[AI Tool Call] Background task error (Sync/Email) for AI appointment: {e}", exc_info=True)
                    # Don't fail the tool call if background tasks fail

                # URL link
                # Appointments go to either calendar or checkout but checkout is specific.
                # Better to link to the daily calendar view for that date
                calendar_link = f"/calendar?date={date}"

                msg = f"Successfully booked appointment for {dog.name} with {groomer.username} on {appt_datetime.astimezone(store_tz).strftime('%Y-%m-%d at %I:%M %p')}. Services added: {services_text or 'None'}. [View Calendar]({calendar_link})"
                current_app.logger.info(f"[AI Tool Call] add_appointment succeeded: {msg}")
                return msg

            except Exception as e:
                db.session.rollback()
                msg = f"Error creating appointment: {str(e)}"
                current_app.logger.error(f"[AI Tool Call] add_appointment exception: {msg}")
                return msg


        def get_groomers(name: str = "") -> list[str]:
            """
            Fetches a list of available groomers (employees) in the store to find their IDs. Use this when you need a groomer's ID to book an appointment.

            Args:
                name: Optional string. The name of the groomer to search for. Leave empty to get a general list.

            Returns:
                A list of strings. Each string contains the groomer's ID and Name. Example: "Groomer ID: 2, Name: Alice"
            """
            query = User.query.filter_by(store_id=store_id, is_groomer=True)
            if name:
                query = query.filter(User.username.ilike(f"%{name}%"))
            groomers = query.limit(10).all()
            if not groomers:
                return ["No groomers found."]
            return [f"Groomer ID: {g.id}, Name: {g.username}" for g in groomers]

        def get_services(name: str = "") -> list[str]:
            """
            Fetches a list of available services in the store to find their IDs and prices.

            Args:
                name: Optional string. The name of the service to search for.

            Returns:
                A list of strings. Each string contains the service's ID, Name, and Base Price. Example: "Service ID: 10, Name: Full Groom, Price: $50.0"
            """
            query = Service.query.filter_by(store_id=store_id)
            if name:
                query = query.filter(Service.name.ilike(f"%{name}%"))
            services_res = query.limit(10).all()
            if not services_res:
                return ["No services found."]
            return [f"Service ID: {s.id}, Name: {s.name}, Price: ${s.base_price}" for s in services_res]

        def add_owner(name: str, phone: str = "", email: str = "") -> str:
            """
            Creates a new owner (client) record in the directory.

            Args:
                name: Required string. The full name of the new owner.
                phone: Optional string. The phone number of the owner. Highly recommended.
                email: Optional string. The email address of the owner.

            Returns:
                A string confirming the creation and providing the new Owner ID, or an error message.
            """
            try:
                owner = Owner(name=name, phone_number=phone, email=email, store_id=store_id)
                db.session.add(owner)
                db.session.commit()
                link = f"/owners/{owner.id}"
                return f"Successfully added owner '{name}' with ID {owner.id}. [View Owner Profile]({link})"
            except Exception as e:
                db.session.rollback()
                return f"Error adding owner: {str(e)}"

        def delete_owner(owner_id: Union[int, str]) -> str:
            """
            Permanently deletes an owner and ALL of their associated dogs and appointments. Ask for confirmation before using this.

            Args:
                owner_id: Required. The integer ID of the owner to delete, OR their exact name as a string.

            Returns:
                A string indicating success or failure of the deletion.
            """
            try:
                owner = None
                if isinstance(owner_id, int) or (isinstance(owner_id, str) and owner_id.isdigit()):
                    owner = Owner.query.filter_by(id=int(owner_id), store_id=store_id).first()
                else:
                    owners = Owner.query.filter(Owner.name.ilike(f"%{owner_id}%"), Owner.store_id == store_id).all()
                    if len(owners) == 1:
                        owner = owners[0]
                    elif len(owners) > 1:
                        return f"Error: Multiple owners found matching '{owner_id}'. Please use get_owners to find the specific ID."

                if not owner:
                    return f"Error: Owner '{owner_id}' not found."

                db.session.delete(owner)
                db.session.commit()
                return f"Successfully deleted owner '{owner.name}' with ID {owner.id}."
            except Exception as e:
                db.session.rollback()
                return f"Error deleting owner: {str(e)}"

        def edit_owner(owner_id: Union[int, str], name: str = "", phone: str = "", email: str = "") -> str:
            """
            Updates the details of an existing owner. Only provide the arguments for the fields that need to change.

            Args:
                owner_id: Required. The integer ID of the owner to edit, OR their name as a string. Using the name is highly encouraged! It will fuzzy match.
                name: Optional string. The new name to set.
                phone: Optional string. The new phone number to set.
                email: Optional string. The new email address to set.

            Returns:
                A string indicating success or failure of the update.
            """
            try:
                owner = None
                if isinstance(owner_id, int) or (isinstance(owner_id, str) and owner_id.isdigit()):
                    owner = Owner.query.filter_by(id=int(owner_id), store_id=store_id).first()
                else:
                    # Try exact match first
                    owners = Owner.query.filter(Owner.name.ilike(owner_id), Owner.store_id == store_id).all()
                    if not owners:
                        # Fallback to fuzzy match
                        owners = Owner.query.filter(Owner.name.ilike(f"%{owner_id}%"), Owner.store_id == store_id).all()
                    if len(owners) == 1:
                        owner = owners[0]
                    elif len(owners) > 1:
                        owner = owners[0]

                if not owner:
                    return f"Error: Owner '{owner_id}' not found."
                if name:
                    owner.name = name
                if phone:
                    owner.phone_number = phone
                if email:
                    owner.email = email
                db.session.commit()
                return f"Successfully updated owner '{owner.name}' with ID {owner.id}."
            except Exception as e:
                db.session.rollback()
                return f"Error editing owner: {str(e)}"

        def add_dog(owner_id: Union[int, str], name: str, breed: str = "") -> str:
            """
            Adds a new dog and attaches it to an existing owner.

            Args:
                owner_id: Required. The integer ID of the owner who owns this dog, OR the owner's name as a string. Using the name is highly encouraged!
                name: Required string. The name of the new dog.
                breed: Optional string. The breed of the dog.

            Returns:
                A string confirming the creation and providing the new Dog ID, or an error message.
            """
            try:
                owner = None
                if isinstance(owner_id, int) or (isinstance(owner_id, str) and owner_id.isdigit()):
                    owner = Owner.query.filter_by(id=int(owner_id), store_id=store_id).first()
                else:
                    # Try exact match first
                    owners = Owner.query.filter(Owner.name.ilike(owner_id), Owner.store_id == store_id).all()
                    if not owners:
                        # Fallback to fuzzy match
                        owners = Owner.query.filter(Owner.name.ilike(f"%{owner_id}%"), Owner.store_id == store_id).all()
                    if len(owners) == 1:
                        owner = owners[0]
                    elif len(owners) > 1:
                        owner = owners[0]

                if not owner:
                    return f"Error: Owner '{owner_id}' not found."

                dog = Dog(name=name, breed=breed, owner_id=owner.id, store_id=store_id)
                db.session.add(dog)
                db.session.commit()
                link = f"/dogs/{dog.id}"
                return f"Successfully added dog '{name}' to owner '{owner.name}'. Dog ID: {dog.id}. [View Dog Profile]({link})"
            except Exception as e:
                db.session.rollback()
                return f"Error adding dog: {str(e)}"

        def edit_dog(dog_id: Union[int, str], name: str = "", breed: str = "") -> str:
            """
            Updates the details of an existing dog. Only provide the arguments for the fields that need to change.

            Args:
                dog_id: Required. The integer ID of the dog to edit, OR their name as a string. Using the name is highly encouraged! It will fuzzy match.
                name: Optional string. The new name to set.
                breed: Optional string. The new breed to set.

            Returns:
                A string indicating success or failure of the update.
            """
            try:
                dog = None
                if isinstance(dog_id, int) or (isinstance(dog_id, str) and dog_id.isdigit()):
                    dog = Dog.query.filter_by(id=int(dog_id), store_id=store_id).first()
                else:
                    # Try exact match first
                    dogs = Dog.query.filter(Dog.name.ilike(dog_id), Dog.store_id == store_id).all()
                    if not dogs:
                        # Fallback to fuzzy match
                        dogs = Dog.query.filter(Dog.name.ilike(f"%{dog_id}%"), Dog.store_id == store_id).all()
                    if len(dogs) == 1:
                        dog = dogs[0]
                    elif len(dogs) > 1:
                        dog = dogs[0]

                if not dog:
                    return f"Error: Dog '{dog_id}' not found."

                if name:
                    dog.name = name
                if breed:
                    dog.breed = breed
                db.session.commit()
                return f"Successfully updated dog '{dog.name}' with ID {dog.id}."
            except Exception as e:
                db.session.rollback()
                return f"Error editing dog: {str(e)}"

        def delete_dog(dog_id: Union[int, str]) -> str:
            """
            Permanently deletes a dog and ALL of their associated appointments. Ask for confirmation before using this.

            Args:
                dog_id: Required. The integer ID of the dog to delete, OR their name as a string. Using the name is highly encouraged!

            Returns:
                A string indicating success or failure of the deletion.
            """
            try:
                dog = None
                if isinstance(dog_id, int) or (isinstance(dog_id, str) and dog_id.isdigit()):
                    dog = Dog.query.filter_by(id=int(dog_id), store_id=store_id).first()
                else:
                    # Try exact match first
                    dogs = Dog.query.filter(Dog.name.ilike(dog_id), Dog.store_id == store_id).all()
                    if not dogs:
                        # Fallback to fuzzy match
                        dogs = Dog.query.filter(Dog.name.ilike(f"%{dog_id}%"), Dog.store_id == store_id).all()
                    if len(dogs) == 1:
                        dog = dogs[0]
                    elif len(dogs) > 1:
                        dog = dogs[0]

                if not dog:
                    return f"Error: Dog '{dog_id}' not found."

                db.session.delete(dog)
                db.session.commit()
                return f"Successfully deleted dog '{dog.name}' with ID {dog.id}."
            except Exception as e:
                db.session.rollback()
                return f"Error deleting dog: {str(e)}"

        def edit_appointment(appointment_id: Union[int, str], date: str = "", time: str = "", groomer_id: Union[int, str] = None, services: list[str] = None, notes: str = "") -> str:
            """
            Modifies an existing appointment. Only provide the arguments for the fields that need to change.

            Args:
                appointment_id: Required. The integer ID of the appointment to edit, OR the dog's name to find their appointment. Using the name is highly encouraged!
                date: Optional string. The new date, strictly in YYYY-MM-DD format. If changing datetime, MUST provide BOTH date and time.
                time: Optional string. The new time, strictly in 24-hour HH:MM format. If changing datetime, MUST provide BOTH date and time.
                groomer_id: Optional. The integer ID of the new groomer, OR the groomer's name as a string. Using the name is highly encouraged!
                services: Optional list of strings. The new list of services (names or IDs) to replace the old ones.
                notes: Optional string. The new notes to set.

            Returns:
                A string indicating success or failure of the update.
            """
            try:
                appt = None
                if isinstance(appointment_id, int) or (isinstance(appointment_id, str) and appointment_id.isdigit()):
                    appt = Appointment.query.options(
                        db.joinedload(Appointment.dog).joinedload(Dog.owner)
                    ).filter_by(id=int(appointment_id), store_id=store_id).first()
                else:
                    # Try exact match first
                    appts = Appointment.query.options(
                        db.joinedload(Appointment.dog).joinedload(Dog.owner)
                    ).join(Dog).filter(
                        Dog.name.ilike(appointment_id),
                        Appointment.store_id == store_id
                    ).all()
                    if not appts:
                        # Fallback to fuzzy match
                        appts = Appointment.query.options(
                            db.joinedload(Appointment.dog).joinedload(Dog.owner)
                        ).join(Dog).filter(
                            Dog.name.ilike(f"%{appointment_id}%"),
                            Appointment.store_id == store_id
                        ).all()
                    if len(appts) == 1:
                        appt = appts[0]
                    elif len(appts) > 1:
                        appt = appts[0]

                if appt is None:
                    return f"Error: Appointment '{appointment_id}' not found."

                store_obj = Store.query.get(store_id)
                store_tz_str = getattr(store_obj, 'timezone', None) or 'America/New_York'
                try:
                    store_tz = pytz.timezone(store_tz_str)
                except pytz.UnknownTimeZoneError:
                    store_tz = pytz.timezone('America/New_York')

                if date and time:
                    try:
                        naive_dt = datetime.datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                        local_dt = store_tz.localize(naive_dt)
                        appt.appointment_datetime = local_dt.astimezone(timezone.utc)
                    except ValueError:
                        return "Error: Invalid date/time format. Expected YYYY-MM-DD and HH:MM."
                elif date or time:
                    return "Error: Both date and time must be provided to update the appointment datetime."

                if groomer_id is not None:
                    groomer = None
                    if isinstance(groomer_id, int) or (isinstance(groomer_id, str) and groomer_id.isdigit()):
                        groomer = User.query.filter_by(id=int(groomer_id), store_id=store_id, is_groomer=True).first()
                    else:
                        # Try exact match first
                        groomers = User.query.filter(User.username.ilike(groomer_id), User.store_id == store_id, User.is_groomer == True).all()
                        if not groomers:
                            # Fallback to fuzzy match
                            groomers = User.query.filter(User.username.ilike(f"%{groomer_id}%"), User.store_id == store_id, User.is_groomer == True).all()
                        if len(groomers) == 1:
                            groomer = groomers[0]
                        elif len(groomers) > 1:
                            groomer = groomers[0]

                    if not groomer:
                        return f"Error: Groomer '{groomer_id}' not found."
                    appt.groomer_id = groomer.id

                services_text = appt.requested_services_text
                if services is not None:
                    services_text_list = []
                    for s in services:
                        s_str = str(s).strip()
                        if s_str.isdigit():
                            service_obj = Service.query.filter_by(id=int(s_str), store_id=store_id).first()
                        else:
                            service_obj = Service.query.filter(Service.name.ilike(s_str), Service.store_id == store_id).first()
                        if service_obj:
                            services_text_list.append(str(service_obj.id))
                    services_text = ','.join(services_text_list)
                    appt.requested_services_text = services_text

                if notes:
                    appt.notes = notes

                db.session.commit()

                try:
                    from management.routes import sync_google_calendar_for_store
                    if store_obj and store_obj.google_token_json and store_obj.google_calendar_id:
                        sync_google_calendar_for_store(store_id)

                    from notifications.email_utils import send_appointment_edited_email
                    if appt.dog.owner:
                        send_appointment_edited_email(store_obj, appt.dog.owner, appt.dog, appt)
                except Exception as e:
                    current_app.logger.error(f"[AI Tool Call] Background task error on edit: {e}")

                appt_time = appt.appointment_datetime.astimezone(store_tz).strftime('%Y-%m-%d at %I:%M %p')
                return f"Successfully updated appointment for {appt.dog.name} on {appt_time}. Services: {services_text or 'None'}."
            except Exception as e:
                db.session.rollback()
                return f"Error editing appointment: {str(e)}"

        def get_current_time() -> str:
            """
            Retrieves the current date and time in the store's local timezone. Use this to orient yourself when the user uses relative terms like "today", "tomorrow", "next Tuesday", or "at 5pm".

            Returns:
                A string containing the current date and time. Example: "Current Date and Time: 2024-10-25 10:30 AM EDT"
            """
            import datetime
            import pytz
            from datetime import timezone

            store_obj = Store.query.get(store_id)
            store_tz_str = getattr(store_obj, 'timezone', None) or 'America/New_York'
            try:
                store_tz = pytz.timezone(store_tz_str)
            except pytz.UnknownTimeZoneError:
                store_tz = pytz.timezone('America/New_York')

            now_utc = datetime.datetime.now(timezone.utc)
            now_local = now_utc.astimezone(store_tz)
            time_str = now_local.strftime('%Y-%m-%d %I:%M %p %Z')
            return f"Current Date and Time: {time_str}"

        def get_daily_appointment_count(date: str = "") -> str:
            """
            Counts the total number of appointments scheduled for a specific date. Useful when the user asks "How many appointments do I have today?" or "How busy is tomorrow?".

            Args:
                date: Optional string. The date to check, strictly in YYYY-MM-DD format (e.g., "2024-10-31"). If left empty, it will default to the current date (today).

            Returns:
                A string stating the number of appointments. Example: "There are 5 appointments scheduled for 2024-10-31."
            """
            import datetime
            import pytz
            from datetime import timezone

            store_obj = Store.query.get(store_id)
            store_tz_str = getattr(store_obj, 'timezone', None) or 'America/New_York'
            try:
                store_tz = pytz.timezone(store_tz_str)
            except pytz.UnknownTimeZoneError:
                store_tz = pytz.timezone('America/New_York')

            if not date:
                now_utc = datetime.datetime.now(timezone.utc)
                now_local = now_utc.astimezone(store_tz)
                target_date = now_local.date()
            else:
                try:
                    target_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
                except ValueError:
                    return "Error: Invalid date format. Expected YYYY-MM-DD."

            naive_start = datetime.datetime.combine(target_date, datetime.time.min)
            naive_end = datetime.datetime.combine(target_date, datetime.time.max)

            local_start = store_tz.localize(naive_start)
            local_end = store_tz.localize(naive_end)

            utc_start = local_start.astimezone(timezone.utc)
            utc_end = local_end.astimezone(timezone.utc)

            count = Appointment.query.filter(
                Appointment.store_id == store_id,
                Appointment.appointment_datetime >= utc_start,
                Appointment.appointment_datetime <= utc_end
            ).count()

            time_str = target_date.strftime('%Y-%m-%d')
            return f"There are {count} appointments scheduled for {time_str}."

        def get_store_info() -> str:
            """
            Retrieves the general business information for the store, such as its name, address, phone number, and operating hours.

            Returns:
                A multi-line string containing the store's details.
            """
            store_obj = Store.query.get(store_id)
            if not store_obj:
                return "Error: Store not found."

            info = []
            info.append(f"Store Name: {store_obj.name}")
            info.append(f"Address: {store_obj.address}")
            info.append(f"Phone: {store_obj.phone}")
            info.append(f"Email: {store_obj.email}")
            info.append(f"Description: {store_obj.description}")
            info.append(f"Business Hours: {store_obj.business_hours}")
            info.append(f"Website: {store_obj.website_url}")
            return "\n".join(info)

        def update_store_info(name: str = None, description: str = None, business_hours: str = None, address: str = None, phone: str = None, email: str = None, website_url: str = None) -> str:
            """
            Updates the store's general business information. Requires the user to have admin privileges. Only provide arguments for the fields being changed.

            Args:
                name: Optional string. New store name.
                description: Optional string. New description.
                business_hours: Optional string. New operating hours.
                address: Optional string. New physical address.
                phone: Optional string. New contact phone number.
                email: Optional string. New contact email.
                website_url: Optional string. New website URL.

            Returns:
                A string indicating success or failure of the update.
            """
            if not g.user.is_admin and g.user.role != 'superadmin':
                return "Error: Only admins can update store information."

            try:
                store_obj = Store.query.get(store_id)
                if not store_obj:
                    return "Error: Store not found."

                if name is not None: store_obj.name = name
                if description is not None: store_obj.description = description
                if business_hours is not None: store_obj.business_hours = business_hours
                if address is not None: store_obj.address = address
                if phone is not None: store_obj.phone = phone
                if email is not None: store_obj.email = email
                if website_url is not None: store_obj.website_url = website_url

                db.session.commit()
                return "Successfully updated store information."
            except Exception as e:
                db.session.rollback()
                return f"Error updating store info: {str(e)}"

        def get_revenue(period: str = "today") -> str:
            """
            Calculates the total revenue earned during a specific time period based on completed appointments. Requires the user to have admin privileges.

            Args:
                period: Optional string. The time frame to calculate. Must be exactly one of: "today", "week", "month", or "year". Defaults to "today".

            Returns:
                A string stating the revenue amount. Example: "Revenue for today: $150.00"
            """
            if not g.user.is_admin and g.user.role != 'superadmin':
                return "Error: Only admins can view revenue information."

            import datetime
            import pytz
            from sqlalchemy import func

            store_obj = Store.query.get(store_id)
            store_tz_str = getattr(store_obj, 'timezone', None) or 'UTC'
            try:
                store_tz = pytz.timezone(store_tz_str)
            except:
                store_tz = pytz.UTC

            now_utc = datetime.datetime.now(timezone.utc)
            now_local = now_utc.astimezone(store_tz)

            start_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + datetime.timedelta(days=1)

            if period == "week":
                start_date = start_date - datetime.timedelta(days=start_date.weekday())
            elif period == "month":
                start_date = start_date.replace(day=1)
            elif period == "year":
                start_date = start_date.replace(month=1, day=1)

            start_utc = start_date.astimezone(timezone.utc)
            end_utc = end_date.astimezone(timezone.utc)

            revenue = db.session.query(func.sum(Appointment.checkout_total_amount)).filter(
                Appointment.store_id == store_id,
                Appointment.status == 'Completed',
                Appointment.appointment_datetime >= start_utc,
                Appointment.appointment_datetime < end_utc
            ).scalar() or 0.0

            return f"Revenue for {period}: ${revenue:.2f}"

        def add_service(name: str, base_price: float, description: str = "") -> str:
            """
            Creates a new service offering for the store. Requires the user to have admin privileges.

            Args:
                name: Required string. The name of the new service (e.g., "Teeth Brushing").
                base_price: Required float. The base cost of the service (e.g., 15.0).
                description: Optional string. Details about what the service includes.

            Returns:
                A string indicating success or failure of the creation.
            """
            if not g.user.is_admin and g.user.role != 'superadmin':
                return "Error: Only admins can add services."

            try:
                service = Service(
                    name=name,
                    base_price=base_price,
                    description=description,
                    store_id=store_id,
                    created_by_user_id=g.user.id
                )
                db.session.add(service)
                db.session.commit()
                return f"Successfully added service '{name}' with base price ${base_price:.2f}."
            except Exception as e:
                db.session.rollback()
                return f"Error adding service: {str(e)}"

        def delete_appointment(appointment_id: Union[int, str], send_notification: bool = True) -> str:
            """
            Cancels and permanently deletes an existing appointment.

            Args:
                appointment_id: Required. The integer ID of the appointment to delete, OR the dog's name to find their appointment. Using the name is highly encouraged!
                send_notification: Optional boolean. Whether to send a cancellation email to the owner. Defaults to True.

            Returns:
                A string indicating success or failure of the cancellation.
            """
            try:
                appt = None
                if isinstance(appointment_id, int) or (isinstance(appointment_id, str) and appointment_id.isdigit()):
                    appt = Appointment.query.options(
                        db.joinedload(Appointment.dog).joinedload(Dog.owner)
                    ).filter_by(id=int(appointment_id), store_id=store_id).first()
                else:
                    # Try exact match first
                    appts = Appointment.query.options(
                        db.joinedload(Appointment.dog).joinedload(Dog.owner)
                    ).join(Dog).filter(
                        Dog.name.ilike(appointment_id),
                        Appointment.store_id == store_id
                    ).all()
                    if not appts:
                        # Fallback to fuzzy match
                        appts = Appointment.query.options(
                            db.joinedload(Appointment.dog).joinedload(Dog.owner)
                        ).join(Dog).filter(
                            Dog.name.ilike(f"%{appointment_id}%"),
                            Appointment.store_id == store_id
                        ).all()
                    if len(appts) == 1:
                        appt = appts[0]
                    elif len(appts) > 1:
                        appt = appts[0]

                if appt is None:
                    return f"Error: Appointment '{appointment_id}' not found."

                store_obj = Store.query.get(store_id)
                store_tz_str = getattr(store_obj, 'timezone', None) or 'America/New_York'
                try:
                    store_tz = pytz.timezone(store_tz_str)
                except pytz.UnknownTimeZoneError:
                    store_tz = pytz.timezone('America/New_York')

                owner = appt.dog.owner if appt.dog else None
                dog = appt.dog
                appt_time = appt.appointment_datetime.astimezone(store_tz).strftime('%Y-%m-%d at %I:%M %p')

                # Background tasks
                try:
                    from utils import get_google_service
                    if store_obj and store_obj.google_token_json and appt.google_event_id:
                        service = get_google_service('calendar', 'v3', store=store_obj)
                        if service:
                            calendar_id = store_obj.google_calendar_id if store_obj.google_calendar_id else 'primary'
                            service.events().delete(calendarId=calendar_id, eventId=appt.google_event_id).execute()

                    if send_notification and owner:
                        from notifications.email_utils import send_appointment_cancelled_email
                        send_appointment_cancelled_email(store_obj, owner, dog, appt)
                except Exception as e:
                    current_app.logger.error(f"[AI Tool Call] Background task error on delete: {e}")

                Receipt.query.filter_by(appointment_id=appt.id).delete(synchronize_session=False)

                db.session.delete(appt)
                db.session.commit()

                return f"Successfully cancelled appointment for {dog.name} on {appt_time}."
            except Exception as e:
                db.session.rollback()
                return f"Error deleting appointment: {str(e)}"

        def get_appointments(date: str = "", dog_name: str = "", owner_name: str = "") -> list[str]:
            """
            Retrieves a list of scheduled appointments. Can be filtered by date, dog name, or owner name. If no filters are provided, it returns a list of all upcoming appointments. Use this when the user asks "What's my schedule like?" or "When is Fido's next appointment?".

            Args:
                date: Optional string. Filter by a specific date, strictly in YYYY-MM-DD format.
                dog_name: Optional string. Filter by a specific dog's name.
                owner_name: Optional string. Filter by a specific owner's name.

            Returns:
                A list of strings. Each string contains the Appointment ID, Date, Time, Dog Name, Owner Name, Groomer Name, and Services. Example: "Appointment ID: 42, Date: 2024-10-31, Time: 02:30 PM, Dog: Rex, Owner: John Smith, Groomer: Alice, Services: Bath, Trim"
            """
            current_app.logger.info(f"[AI Tool Call] get_appointments called with date='{date}', dog_name='{dog_name}', owner_name='{owner_name}'")

            store_obj = Store.query.get(store_id)
            store_tz_str = getattr(store_obj, 'timezone', None) or 'America/New_York'
            try:
                store_tz = pytz.timezone(store_tz_str)
            except pytz.UnknownTimeZoneError:
                store_tz = pytz.timezone('America/New_York')

            query = Appointment.query.options(
                db.joinedload(Appointment.dog).joinedload(Dog.owner),
                db.joinedload(Appointment.groomer)
            ).filter(Appointment.store_id == store_id)

            if date:
                try:
                    # Filter by the entire day in the store's timezone
                    naive_start = datetime.datetime.strptime(f"{date} 00:00", "%Y-%m-%d %H:%M")
                    naive_end = datetime.datetime.strptime(f"{date} 23:59", "%Y-%m-%d %H:%M")
                    local_start = store_tz.localize(naive_start)
                    local_end = store_tz.localize(naive_end)
                    utc_start = local_start.astimezone(timezone.utc)
                    utc_end = local_end.astimezone(timezone.utc)
                    query = query.filter(Appointment.appointment_datetime >= utc_start, Appointment.appointment_datetime <= utc_end)
                except ValueError:
                    return ["Error: Invalid date format. Expected YYYY-MM-DD."]
            else:
                # Default to upcoming appointments if no date given
                now_utc = datetime.datetime.now(timezone.utc)
                query = query.filter(Appointment.appointment_datetime >= now_utc)

            if dog_name:
                query = query.join(Dog).filter(Dog.name.ilike(f"%{dog_name}%"))
            if owner_name:
                # If we didn't already join dog, join it
                if not dog_name:
                    query = query.join(Dog)
                query = query.join(Owner).filter(Owner.name.ilike(f"%{owner_name}%"))

            appts = query.order_by(Appointment.appointment_datetime.asc()).limit(15).all()

            if not appts:
                current_app.logger.info(f"[AI Tool Call] get_appointments returning 'No appointments found.'")
                return ["No appointments found matching those criteria."]

            result = []
            for a in appts:
                local_dt = a.appointment_datetime.astimezone(store_tz)
                date_str = local_dt.strftime('%Y-%m-%d')
                time_str = local_dt.strftime('%I:%M %p')
                dog_n = a.dog.name if a.dog else "Unknown"
                owner_n = a.dog.owner.name if a.dog and a.dog.owner else "Unknown"
                groomer_n = a.groomer.username if a.groomer else "Unknown"
                services = a.requested_services_text or "None"

                result.append(f"Appointment ID: {a.id}, Date: {date_str}, Time: {time_str}, Dog: {dog_n}, Owner: {owner_n}, Groomer: {groomer_n}, Services: {services}")

            current_app.logger.info(f"[AI Tool Call] get_appointments returning {len(result)} appointments.")
            return result


        def sync_calendar() -> str:
            """
            Manually triggers a synchronization of the store's appointments with their connected Google Calendar.
            Use this only when the user explicitly asks to sync the calendar.

            Returns:
                A string indicating success or failure.
            """
            current_app.logger.info(f"[AI Tool Call] sync_calendar called")
            try:
                store_obj = Store.query.get(store_id)
                if not store_obj or not store_obj.google_token_json or not store_obj.google_calendar_id:
                    return "Failed to sync calendar. Make sure the store has connected their Google account and selected a calendar."

                from management.routes import sync_google_calendar_for_store
                success, msg = sync_google_calendar_for_store(store_id)
                if success:
                    return f"Successfully synchronized calendar: {msg}"
                else:
                    return f"Calendar sync failed: {msg}"
            except Exception as e:
                current_app.logger.error(f"[AI Tool Call] Error in sync_calendar: {e}")
                return f"Error syncing calendar: {str(e)}"

        def send_email(owner_id: Union[int, str], subject: str, message: str) -> str:
            """
            Sends a custom email to an owner. Make sure you ask the user for confirmation and show them the drafted message before sending it.

            Args:
                owner_id: Required. The integer ID of the owner, or their name as a string.
                subject: Required string. The subject line of the email.
                message: Required string. The main body of the email.

            Returns:
                A string indicating success or failure.
            """
            current_app.logger.info(f"[AI Tool Call] send_email called with owner_id={owner_id}")
            try:
                owner = None
                if isinstance(owner_id, int) or (isinstance(owner_id, str) and owner_id.isdigit()):
                    owner = Owner.query.filter_by(id=int(owner_id), store_id=store_id).first()
                else:
                    owners = Owner.query.filter(Owner.name.ilike(f"%{owner_id}%"), Owner.store_id == store_id).all()
                    if len(owners) == 1:
                        owner = owners[0]
                    elif len(owners) > 1:
                        return f"Multiple owners found matching '{owner_id}'. Please use the specific Owner ID."

                if not owner:
                    return f"Owner '{owner_id}' not found."

                store_obj = Store.query.get(store_id)
                from notifications.email_utils import send_custom_email
                success = send_custom_email(store_obj, owner, subject, message)

                if success:
                    return f"Successfully sent email to {owner.name}."
                else:
                    return f"Failed to send email to {owner.name}. Make sure the store has email integration configured and the owner has a valid email address."
            except Exception as e:
                current_app.logger.error(f"[AI Tool Call] Error in send_email: {e}")
                return f"Error sending email: {str(e)}"

        def send_text(owner_id: Union[int, str], message: str) -> str:
            """
            Sends a custom text message to an owner. Make sure you ask the user for confirmation and show them the drafted message before sending it.

            Args:
                owner_id: Required. The integer ID of the owner, or their name as a string.
                message: Required string. The main body of the text message.

            Returns:
                A string indicating success or failure.
            """
            current_app.logger.info(f"[AI Tool Call] send_text called with owner_id={owner_id}")
            try:
                owner = None
                if isinstance(owner_id, int) or (isinstance(owner_id, str) and owner_id.isdigit()):
                    owner = Owner.query.filter_by(id=int(owner_id), store_id=store_id).first()
                else:
                    owners = Owner.query.filter(Owner.name.ilike(f"%{owner_id}%"), Owner.store_id == store_id).all()
                    if len(owners) == 1:
                        owner = owners[0]
                    elif len(owners) > 1:
                        return f"Multiple owners found matching '{owner_id}'. Please use the specific Owner ID."

                if not owner:
                    return f"Owner '{owner_id}' not found."

                store_obj = Store.query.get(store_id)
                from notifications.email_utils import send_custom_text
                success = send_custom_text(store_obj, owner, message)

                if success:
                    return f"Successfully sent text message to {owner.name}."
                else:
                    return f"Failed to send text to {owner.name}. Make sure the store has email/text integration configured and the owner has a valid phone number/carrier."
            except Exception as e:
                current_app.logger.error(f"[AI Tool Call] Error in send_text: {e}")
                return f"Error sending text message: {str(e)}"


        system_prompt = f"""
        Role: You are the "Pawfection Business Agent." You are a highly efficient, professional administrative assistant for pet grooming businesses.

        Core Objective: Help the user manage their Client & Pet Directory and Schedule New Appointments with 100% accuracy and structured data.
        You are primarily powered by Gemini 3.1 Flash-Lite, but may fallback to a local model (like qwen2.5-coder) if rate limits are reached.

        CONTEXT:
        Current User Role: {g.user.role if hasattr(g, 'user') else 'Unknown'}
        Current User ID: {g.user.id if hasattr(g, 'user') else 'Unknown'}
        {context_data}

        # PRIMARY INSTRUCTIONS (For Gemini and General Operation):
        As the primary virtual assistant handling business operations:
        When the user asks you to send an email or a text to a certain customer:
        1. Ask the user for the message they want to send.
        2. Attempt to draft it to make it look and sound professional.
        3. Give the user the option of using their original message or your updated version.
        4. Wait for their confirmation before calling the send_email or send_text tool.

        1. Identify Intent: Determine if the user wants to ADD, EDIT, DELETE, or VIEW a record (Owner, Dog, Appointment, Service, Store Info, Revenue). Note: Ensure you account for relative dates/times provided by the user using the Current Date and Time context provided to you. For example, if today is Tuesday, and the user asks for "next Wednesday", you must calculate what date next Wednesday is based on the Current Date and Time context before making tool calls.

        2. Lookups & Actions:
           - To book an appointment, use `add_appointment`. Use the names provided by the user for dogs, groomers, and services. Only ask for clarification if a required piece of information is missing (like date or time), but do not ask for IDs. If you have the dog's name, groomer's name, date, time, and service, CALL THE TOOL IMMEDIATELY.
           - To edit or delete, use the names provided by the user (like Dog Name or Owner Name) as the IDs in the tools. DO NOT ask the user for IDs.
           - Note: When you use `add_appointment`, `edit_appointment`, or `delete_appointment`, the system automatically syncs with the connected Google Calendar and sends the appropriate email/text notifications to the customer from the connected Google account. You do not need to manually call `send_email` or `send_text` after booking an appointment.

           - If a tool fails (e.g., because a name is ambiguous or not found), THEN use `get_dogs`, `get_owners`, `get_groomers`, or `get_appointments` to find the correct details, and try the action again. DO NOT tell the user to find the ID.
           - Only use the exact parameters requested by the tools.
           - IMPORTANT: When a user gives you information, DO NOT ask them for it again. If you ask a clarifying question and they answer, use that answer and immediately call the relevant tool.
           - IMPORTANT: DO NOT claim to have booked an appointment or completed an action unless you have successfully called the tool and received a success message back.

        3. Safety Check: Always confirm before performing a DELETE action.

        4. Output Formatting:
           - Provide a polite, concise confirmation to the user AFTER a successful tool call.
           - To perform actions, use the provided tools via the native tool calling framework.
           - Use a helpful, organized tone—break down multi-step processes into bulleted lists for clarity.
           - Never output JSON or any other code in the chat for users to see.

        ADDITIONAL INSTRUCTIONS:
        - DO NOT OFFER CHOICES OR WALKTHROUGHS. When a user wants to perform an action, call the relevant tool immediately to perform the action in the background. DO NOT offer a "smart link" or ask them to fill out a form themselves. You handle everything fully.
        - When calling a tool, wait for its output and confirm the result with the user. DO NOT use made-up tool names.
        - You can manage the business: use `get_revenue` to check earnings, `get_store_info` to see settings, and `update_store_info` / `add_service` to change them (these require admin privileges).
        - To get appointment details, use `get_appointments`. Do not make the user look up IDs. You can also use `get_daily_appointment_count` to find out how many appointments exist on a particular date.
        - Only use the tools provided to you. If a task cannot be fully completed by a tool, inform the user.
        - Use Markdown for formatting (bold, lists, links).

        # FALLBACK INSTRUCTIONS (Strict formatting for local Ollama models like qwen2.5-coder):
        If you are the fallback local model, you MUST adhere to the following formatting rules when calling tools:
        - DO NOT generate raw JSON strings in your conversational response.
        - DO NOT output code blocks or markdown code syntax containing tool calls.
        - If the native tool calling framework fails and you MUST output JSON to call a tool, format it EXACTLY like this on its own line: {{"name": "tool_name", "arguments": {{"arg1": "value1"}}}}
        """





        tools = [get_dogs, get_owners, add_appointment, get_groomers, get_services, add_owner, edit_owner, delete_owner, add_dog, edit_dog, delete_dog, edit_appointment, delete_appointment, get_store_info, update_store_info, get_revenue, add_service, get_appointments, get_current_time, get_daily_appointment_count, send_email, send_text, sync_calendar]

        formatted_history = [{"role": "system", "content": system_prompt}]
        for msg in history:
            role = msg.get('role', 'user')
            if role not in ['user', 'model']:
                continue
            role = 'assistant' if role == 'model' else 'user'
            text = msg.get('text', '')
            import re
            clean_text = re.sub('<[^<]+>', '', text) if role == 'assistant' else text
            formatted_history.append({"role": role, "content": clean_text})

        formatted_history.append({"role": "user", "content": user_message})

        # Define a tool mapping dictionary
        available_tools = {tool.__name__: tool for tool in tools}

        response_text = ""
        try:
            # 1. Primary AI: Gemini
            genai_history = []
            for msg in history:
                role = msg.get('role', 'user')
                if role not in ['user', 'model']:
                    continue
                text = msg.get('text', '')
                import re
                clean_text = re.sub('<[^<]+>', '', text) if role == 'model' else text
                genai_history.append({"role": role, "parts": [{"text": clean_text}]})

            chat = client.chats.create(
                model='gemini-2.5-flash',
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=tools,
                    temperature=0.7,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False),
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode='AUTO')
                    )
                ),
                history=genai_history
            )

            gemini_response = chat.send_message(user_message)
            response_text = gemini_response.text
            current_app.logger.info(f"[Gemini Response] Result text: '{response_text}'")
            if getattr(gemini_response, 'function_calls', None):
                current_app.logger.info(f"[Gemini Response] Function calls: {gemini_response.function_calls}")

        except Exception as gemini_error:
            current_app.logger.warning(f"[AI Chat Fallback] Gemini failed: {gemini_error}. Falling back to Ollama.")

            # 2. Fallback AI: Ollama
            ollama_url = os.environ.get('OLLAMA_URL')
            ollama_model = os.environ.get('OLLAMA_MODEL')

            if not ollama_url or not ollama_model:
                raise ValueError("OLLAMA_URL and OLLAMA_MODEL must be explicitly set in environment variables.")

            current_app.logger.info(f"[AI Chat Request] Attempting Ollama ({ollama_model}) at {ollama_url}")

            ollama_client = ollama.Client(host=ollama_url)
            response = ollama_client.chat(
                model=ollama_model,
                messages=formatted_history,
                tools=tools
            )

            import json

            def extract_json_from_text(text):
                import re

                # First try code blocks
                code_blocks = re.findall(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
                for block in code_blocks:
                    try:
                        return json.loads(block)
                    except json.JSONDecodeError:
                        pass

                # Then try to find raw JSON objects in the text that have "name" and "arguments"
                match = re.search(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\}', text, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(0))
                    except json.JSONDecodeError:
                        pass

                return None

            # Process tool calls in a loop (handle both native and fallback)
            max_loops = 3
            loop_count = 0

            while loop_count < max_loops:
                loop_count += 1

                # Native Tool Calling
                if response.message.tool_calls:
                    formatted_history.append(response.message)
                    for tool_call in response.message.tool_calls:
                        function_name = tool_call.function.name
                        arguments = tool_call.function.arguments

                        current_app.logger.info(f"[Ollama Tool Call] {function_name} with args: {arguments}")

                        if function_name in available_tools:
                            try:
                                function_to_call = available_tools[function_name]
                                function_response = function_to_call(**arguments)
                            except Exception as e:
                                function_response = f"Error executing tool {function_name}: {e}"
                        else:
                            function_response = f"Tool {function_name} not found."

                        current_app.logger.info(f"[Ollama Tool Response] {function_response}")

                        formatted_history.append({
                            'role': 'tool',
                            'content': str(function_response),
                        })

                    # Send the tool responses back to Ollama to get the final answer
                    response = ollama_client.chat(
                        model=ollama_model,
                        messages=formatted_history,
                        tools=tools
                    )

                # Fallback: Manual JSON Parsing
                elif response.message.content:
                    extracted_json = extract_json_from_text(response.message.content)
                    if extracted_json and 'name' in extracted_json and 'arguments' in extracted_json:
                        function_name = extracted_json['name']
                        arguments = extracted_json['arguments']

                        current_app.logger.info(f"[Ollama Fallback Tool Call] {function_name} with args: {arguments}")

                        # Add assistant message with the thought process but strip the JSON for the final output
                        clean_content = response.message.content
                        if extracted_json:
                            # Try to strip the json representation
                            try:
                                json_str = json.dumps(extracted_json)
                                clean_content = clean_content.replace(json_str, "")
                            except:
                                pass

                            # Strip code blocks
                            clean_content = re.sub(r'```(?:json)?\s*.*?\s*```', '', clean_content, flags=re.DOTALL)
                            # Strip raw tool calls
                            clean_content = re.sub(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\}', '', clean_content, flags=re.DOTALL)

                        formatted_history.append({'role': 'assistant', 'content': clean_content})

                        if function_name in available_tools:
                            try:
                                function_to_call = available_tools[function_name]
                                function_response = function_to_call(**arguments)
                            except Exception as e:
                                function_response = f"Error executing tool {function_name}: {e}"
                        else:
                            function_response = f"Tool {function_name} not found."

                        current_app.logger.info(f"[Ollama Fallback Tool Response] {function_response}")

                        formatted_history.append({
                            'role': 'tool',
                            'content': str(function_response),
                        })

                        # Send the tool responses back to Ollama to get the final answer
                        response = ollama_client.chat(
                            model=ollama_model,
                            messages=formatted_history,
                            tools=tools
                        )

                        # Break loop if the new response still contains the exact same tool call (infinite loop prevention)
                        new_extracted = extract_json_from_text(response.message.content)
                        if new_extracted and new_extracted.get('name') == function_name and new_extracted.get('arguments') == arguments:
                            current_app.logger.warning(f"[Ollama Fallback] Breaking loop due to repeated identical tool call: {function_name}")
                            break
                    else:
                        break # No native tools, no fallback tools found. Break loop.
                else:
                    break # No content and no tool calls. Break loop.

            response_text = response.message.content
            # Make absolutely sure we strip out JSON from the final response text
            if response_text:
                import re
                response_text = re.sub(r'```(?:json)?\s*.*?\s*```', '', response_text, flags=re.DOTALL)
                response_text = re.sub(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\}', '', response_text, flags=re.DOTALL)
            current_app.logger.info(f"[Ollama Response] Result text: '{response_text}'")

        # Convert Markdown to HTML for safe rendering on frontend
        html_response = markdown.markdown(response_text if response_text else "")

        return jsonify({"response": html_response})

    except Exception as e:
        current_app.logger.error(f"AI Chat Error: {e}", exc_info=True)
        return jsonify({"error": "I'm having trouble connecting to my brain right now. Please try again later."}), 500
