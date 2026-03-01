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
from models import Service, Dog, Owner, Appointment, User, Store
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
                context_data += f"\nAvailable Services: {service_list}"
            except Exception as e:
                current_app.logger.warning(f"AI Context Error (Services): {e}")

        def get_dogs(name: str = "") -> list[str]:
            """
            Fetches a list of dogs in the store. Optionally filters by name.

            Args:
                name: Optional dog name to filter by.

            Returns:
                A list of strings containing dog details (name, breed, dog_id).
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
            Fetches a list of owners in the store. Optionally filters by name.

            Args:
                name: Optional owner name to filter by.

            Returns:
                A list of strings containing owner details (name, phone, owner_id).
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

        def add_appointment(dog_id: int, date: str, time: str, groomer_id: int, services: list[str], notes: str = "") -> str:
            """
            Creates a new appointment for a dog, fully configured with groomer and services.
            Sends notifications and syncs with Google Calendar.

            Args:
                dog_id: The ID of the dog.
                date: The date of the appointment in YYYY-MM-DD format.
                time: The time of the appointment in HH:MM format (24-hour).
                groomer_id: The ID of the selected groomer.
                services: A list of service names or service IDs to attach to the appointment.
                notes: Optional notes for the appointment.

            Returns:
                A string indicating success or failure.
            """
            current_app.logger.info(f"[AI Tool Call] add_appointment called with dog_id={dog_id}, groomer_id={groomer_id}, date='{date}', time='{time}', services='{services}', notes='{notes}'")
            try:
                dog = Dog.query.options(db.joinedload(Dog.owner)).filter_by(id=dog_id, store_id=store_id).first()
                if not dog:
                    return f"Error: Dog with ID {dog_id} not found."

                groomer = User.query.filter_by(id=groomer_id, store_id=store_id, is_groomer=True).first()
                if not groomer:
                    return f"Error: Groomer with ID {groomer_id} not found or is not a valid groomer."

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
                    from management.routes import sync_google_calendar_for_store
                    if store_obj and store_obj.google_token_json and store_obj.google_calendar_id:
                        sync_google_calendar_for_store(store_id)

                    # Reload appointment with relationships
                    new_appt = Appointment.query.options(
                        db.joinedload(Appointment.dog).joinedload(Dog.owner),
                        db.joinedload(Appointment.groomer)
                    ).filter_by(id=appt.id).first()

                    if dog.owner:
                        send_appointment_confirmation_email(store_obj, dog.owner, dog, new_appt, groomer=groomer, services_text=services_text)
                except Exception as e:
                    current_app.logger.error(f"[AI Tool Call] Background task error (Sync/Email) for AI appointment: {e}", exc_info=True)
                    # Don't fail the tool call if background tasks fail

                msg = f"Successfully booked appointment for {dog.name} with {groomer.username} on {appt_datetime.astimezone(store_tz).strftime('%Y-%m-%d at %I:%M %p')}. Services added: {services_text or 'None'}."
                current_app.logger.info(f"[AI Tool Call] add_appointment succeeded: {msg}")
                return msg

            except Exception as e:
                db.session.rollback()
                msg = f"Error creating appointment: {str(e)}"
                current_app.logger.error(f"[AI Tool Call] add_appointment exception: {msg}")
                return msg


        def get_groomers(name: str = "") -> list[str]:
            """
            Fetches a list of available groomers in the store. Optionally filters by name.

            Args:
                name: Optional groomer name to filter by.

            Returns:
                A list of strings containing groomer details (name, user_id).
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
            Fetches a list of available services in the store. Optionally filters by name.

            Args:
                name: Optional service name to filter by.

            Returns:
                A list of strings containing service details (name, service_id, base_price).
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
            Adds a new owner to the store.

            Args:
                name: The full name of the owner.
                phone: Optional phone number.
                email: Optional email address.

            Returns:
                A string indicating success or failure.
            """
            try:
                owner = Owner(name=name, phone_number=phone, email=email, store_id=store_id)
                db.session.add(owner)
                db.session.commit()
                return f"Successfully added owner '{name}' with ID {owner.id}."
            except Exception as e:
                db.session.rollback()
                return f"Error adding owner: {str(e)}"

        def delete_owner(owner_id: int) -> str:
            """
            Deletes an existing owner from the store. This will also delete all associated dogs and appointments.

            Args:
                owner_id: The ID of the owner to delete.

            Returns:
                A string indicating success or failure.
            """
            try:
                owner = Owner.query.filter_by(id=owner_id, store_id=store_id).first()
                if not owner:
                    return f"Error: Owner with ID {owner_id} not found."

                db.session.delete(owner)
                db.session.commit()
                return f"Successfully deleted owner '{owner.name}' with ID {owner.id}."
            except Exception as e:
                db.session.rollback()
                return f"Error deleting owner: {str(e)}"

        def edit_owner(owner_id: int, name: str = "", phone: str = "", email: str = "") -> str:
            """
            Edits an existing owner in the store. Provide only the fields you want to change.

            Args:
                owner_id: The ID of the owner to edit.
                name: The new full name of the owner.
                phone: The new phone number.
                email: The new email address.

            Returns:
                A string indicating success or failure.
            """
            try:
                owner = Owner.query.filter_by(id=owner_id, store_id=store_id).first()
                if not owner:
                    return f"Error: Owner with ID {owner_id} not found."
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

        def add_dog(owner_id: int, name: str, breed: str = "") -> str:
            """
            Adds a new dog to an existing owner's profile.

            Args:
                owner_id: The ID of the dog's owner.
                name: The name of the dog.
                breed: Optional breed of the dog.

            Returns:
                A string indicating success or failure.
            """
            try:
                owner = Owner.query.filter_by(id=owner_id, store_id=store_id).first()
                if not owner:
                    return f"Error: Owner with ID {owner_id} not found."

                dog = Dog(name=name, breed=breed, owner_id=owner.id, store_id=store_id)
                db.session.add(dog)
                db.session.commit()
                return f"Successfully added dog '{name}' to owner '{owner.name}'. Dog ID: {dog.id}."
            except Exception as e:
                db.session.rollback()
                return f"Error adding dog: {str(e)}"

        def edit_dog(dog_id: int, name: str = "", breed: str = "") -> str:
            """
            Edits an existing dog in the store. Provide only the fields you want to change.

            Args:
                dog_id: The ID of the dog to edit.
                name: The new name of the dog.
                breed: The new breed of the dog.

            Returns:
                A string indicating success or failure.
            """
            try:
                dog = Dog.query.filter_by(id=dog_id, store_id=store_id).first()
                if not dog:
                    return f"Error: Dog with ID {dog_id} not found."

                if name:
                    dog.name = name
                if breed:
                    dog.breed = breed
                db.session.commit()
                return f"Successfully updated dog '{dog.name}' with ID {dog.id}."
            except Exception as e:
                db.session.rollback()
                return f"Error editing dog: {str(e)}"

        def delete_dog(dog_id: int) -> str:
            """
            Deletes an existing dog from the store. This will also delete all associated appointments.

            Args:
                dog_id: The ID of the dog to delete.

            Returns:
                A string indicating success or failure.
            """
            try:
                dog = Dog.query.filter_by(id=dog_id, store_id=store_id).first()
                if not dog:
                    return f"Error: Dog with ID {dog_id} not found."

                db.session.delete(dog)
                db.session.commit()
                return f"Successfully deleted dog '{dog.name}' with ID {dog.id}."
            except Exception as e:
                db.session.rollback()
                return f"Error deleting dog: {str(e)}"

        def edit_appointment(appointment_id: int, date: str = "", time: str = "", groomer_id: int = None, services: list[str] = None, notes: str = "") -> str:
            """
            Edits an existing appointment. Sends notifications and syncs with Google Calendar. Provide only the fields you want to change.

            Args:
                appointment_id: The ID of the appointment to edit.
                date: The new date of the appointment in YYYY-MM-DD format.
                time: The new time of the appointment in HH:MM format (24-hour).
                groomer_id: The ID of the new groomer.
                services: A list of new service names or service IDs to attach to the appointment.
                notes: The new notes for the appointment.

            Returns:
                A string indicating success or failure.
            """
            try:
                appt = Appointment.query.options(
                    db.joinedload(Appointment.dog).joinedload(Dog.owner)
                ).filter_by(id=appointment_id, store_id=store_id).first()

                if not appt:
                    return f"Error: Appointment {appointment_id} not found."

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
                    groomer = User.query.filter_by(id=groomer_id, store_id=store_id, is_groomer=True).first()
                    if not groomer:
                        return f"Error: Groomer with ID {groomer_id} not found or is not a valid groomer."
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

        def delete_appointment(appointment_id: int, send_notification: bool = True) -> str:
            """
            Cancels/deletes an existing appointment.

            Args:
                appointment_id: The ID of the appointment to delete.
                send_notification: Whether to send a cancellation email/text to the owner.

            Returns:
                A string indicating success or failure.
            """
            try:
                appt = Appointment.query.options(
                    db.joinedload(Appointment.dog).joinedload(Dog.owner)
                ).filter_by(id=appointment_id, store_id=store_id).first()

                if not appt:
                    return f"Error: Appointment {appointment_id} not found."

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
                    from management.routes import sync_google_calendar_for_store
                    if store_obj and store_obj.google_token_json and store_obj.google_calendar_id:
                        sync_google_calendar_for_store(store_id)

                    if send_notification and owner:
                        from notifications.email_utils import send_appointment_cancelled_email
                        send_appointment_cancelled_email(store_obj, owner, dog, appt)
                except Exception as e:
                    current_app.logger.error(f"[AI Tool Call] Background task error on delete: {e}")

                db.session.delete(appt)
                db.session.commit()

                return f"Successfully cancelled appointment for {dog.name} on {appt_time}."
            except Exception as e:
                db.session.rollback()
                return f"Error deleting appointment: {str(e)}"

        system_prompt = f"""
        You are 'Pawfection AI', a helpful assistant for a dog grooming business app.
        Your goal is to help staff manage appointments, owners, and dogs.

        The app has the following main features and routes:
        - Dashboard: /dashboard
        - Calendar: /calendar
        - Add Appointment: /add_appointment (Params: dog_id, date, time, groomer_id, services, notes)
        - Add Owner: /add_owner
        - Add Dog: /add_dog
        - Directory: /directory (List of owners/dogs)

        CONTEXT:
        Current User Role: {g.user.role if hasattr(g, 'user') else 'Unknown'}
        Current User ID: {g.user.id if hasattr(g, 'user') else 'Unknown'}
        {context_data}

        INSTRUCTIONS:
        1. Be concise, friendly, and professional.
        2. You now have tools to look up groomers, services, dogs, owners, and to create/edit/delete appointments, owners, and dogs directly!
        3. ALWAYS OFFER A CHOICE FOR BOOKING: When a user wants to book an appointment, ask if they want you to "book it automatically in the background" or "provide a link to the booking page with the details filled out".
           - If they choose automatic: You MUST gather all required details (dog, date, time, groomer, and services) before calling the `add_appointment` tool. Use your lookup tools to find the correct IDs for groomer and dog, and the correct names/IDs for services.
           - If they choose the link: Generate a SMART LINK to `/add_appointment` with the parameters pre-filled (e.g., `[Book for Rex](/add_appointment?dog_id=1&date=2023-10-10&time=14:00&groomer_id=2&services=Bath,Nails)`).
        4. When calling a tool, wait for its output and confirm the result with the user.
        5. If you need to perform an action without a tool, generate a SMART LINK.
        6. When editing profiles (owner or dog), prompt the user what part of the profile they'd like to edit.
        7. Use Markdown for formatting (bold, lists, links).
        """


        tools = [get_dogs, get_owners, add_appointment, get_groomers, get_services, add_owner, edit_owner, delete_owner, add_dog, edit_dog, delete_dog, edit_appointment, delete_appointment]

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
            # 1. Primary AI: Ollama
            ollama_url = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
            ollama_model = os.environ.get('OLLAMA_MODEL', 'Gemma3:12b')
            current_app.logger.info(f"[AI Chat Request] Attempting Ollama ({ollama_model}) at {ollama_url}")

            ollama_client = ollama.Client(host=ollama_url)
            response = ollama_client.chat(
                model=ollama_model,
                messages=formatted_history,
                tools=tools
            )

            # Process tool calls in a loop
            while response.message.tool_calls:
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

            response_text = response.message.content
            current_app.logger.info(f"[Ollama Response] Result text: '{response_text}'")

        except Exception as ollama_error:
            current_app.logger.warning(f"[AI Chat Fallback] Ollama failed: {ollama_error}. Falling back to Gemini.")

            # 2. Fallback AI: Gemini
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
                model='gemini-flash-latest',
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

        # Convert Markdown to HTML for safe rendering on frontend
        html_response = markdown.markdown(response_text if response_text else "")

        return jsonify({"response": html_response})

    except Exception as e:
        current_app.logger.error(f"AI Chat Error: {e}", exc_info=True)
        return jsonify({"error": "I'm having trouble connecting to my brain right now. Please try again later."}), 500
