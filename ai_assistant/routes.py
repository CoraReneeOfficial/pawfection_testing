from flask import Blueprint, request, jsonify, render_template, current_app, session, g
from ai_assistant.feature_flag import is_ai_enabled
from google import genai
from google.genai import types
import os
import markdown
import datetime
from datetime import timezone
from functools import wraps
from models import Service, Dog, Owner, Appointment
from extensions import db

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
    if not user_message:
        return jsonify({"error": "No message provided."}), 400

    current_app.logger.info(f"[AI Chat Request] Received message: '{user_message}'")

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

        def add_appointment(dog_id: int, date: str, time: str, notes: str = "") -> str:
            """
            Creates a new appointment for a dog.

            Args:
                dog_id: The ID of the dog.
                date: The date of the appointment in YYYY-MM-DD format.
                time: The time of the appointment in HH:MM format (24-hour).
                notes: Optional notes for the appointment.

            Returns:
                A string indicating success or failure.
            """
            current_app.logger.info(f"[AI Tool Call] add_appointment called with dog_id={dog_id}, date='{date}', time='{time}', notes='{notes}'")
            try:
                dog = Dog.query.filter_by(id=dog_id, store_id=store_id).first()
                if not dog:
                    msg = f"Error: Dog with ID {dog_id} not found."
                    current_app.logger.info(f"[AI Tool Call] add_appointment failed: {msg}")
                    return msg

                # Combine date and time
                dt_str = f"{date} {time}"
                appt_datetime = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M")

                appt = Appointment(
                    dog_id=dog.id,
                    appointment_datetime=appt_datetime,
                    notes=notes,
                    store_id=store_id,
                    created_by_user_id=g.user.id
                )
                db.session.add(appt)
                db.session.commit()
                msg = f"Successfully booked appointment for {dog.name} on {appt_datetime.strftime('%Y-%m-%d at %I:%M %p')}."
                current_app.logger.info(f"[AI Tool Call] add_appointment succeeded: {msg}")
                return msg
            except Exception as e:
                db.session.rollback()
                msg = f"Error creating appointment: {str(e)}"
                current_app.logger.error(f"[AI Tool Call] add_appointment exception: {msg}")
                return msg

        system_prompt = f"""
        You are 'Pawfection AI', a helpful assistant for a dog grooming business app.
        Your goal is to help staff manage appointments, owners, and dogs.

        The app has the following main features and routes:
        - Dashboard: /dashboard
        - Calendar: /calendar
        - Add Appointment: /add_appointment (Params: dog_id, appointment_date, appointment_time, notes)
        - Add Owner: /add_owner
        - Add Dog: /add_dog
        - Directory: /directory (List of owners/dogs)

        CONTEXT:
        Current User Role: {g.user.role if hasattr(g, 'user') else 'Unknown'}
        Current User ID: {g.user.id if hasattr(g, 'user') else 'Unknown'}
        {context_data}

        INSTRUCTIONS:
        1. Be concise, friendly, and professional.
        2. You now have tools to look up dogs, look up owners, and create appointments directly. Use them!
        3. If you create an appointment, confirm the details with the user using the tool output.
        4. If you need to perform an action but don't have a tool for it (like adding a new owner or dog), generate a SMART LINK in Markdown format to guide the user to the correct page.
           - Format: `[Action Name](URL)`
           - Example: `[Book Appointment for Rex](/add_appointment?notes=Bath&date=2023-10-10)`
        5. Use Markdown for formatting (bold, lists, links).
        """

        chat = client.chats.create(
            model='gemini-flash-latest',
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[get_dogs, get_owners, add_appointment],
                temperature=0.7,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False),
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode='AUTO')
                )
            )
        )

        response = chat.send_message(user_message)

        current_app.logger.info(f"[AI Chat Response] Result text: '{response.text}'")
        if getattr(response, 'function_calls', None):
            current_app.logger.info(f"[AI Chat Response] Function calls: {response.function_calls}")
        if getattr(response, 'candidates', None) and response.candidates:
            current_app.logger.info(f"[AI Chat Response] Finish reason: {response.candidates[0].finish_reason}")

        # Convert Markdown to HTML for safe rendering on frontend
        html_response = markdown.markdown(response.text if response.text else "")

        return jsonify({"response": html_response})

    except Exception as e:
        current_app.logger.error(f"AI Chat Error: {e}", exc_info=True)
        return jsonify({"error": "I'm having trouble connecting to my brain right now. Please try again later."}), 500
