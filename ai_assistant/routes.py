from flask import Blueprint, request, jsonify, render_template, current_app, session, g
from ai_assistant.feature_flag import is_ai_enabled
import google.generativeai as genai
import os
import markdown
from functools import wraps
from models import Service, Dog, Owner

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

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"error": "AI configuration error: Missing API Key."}), 500

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

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
        {context_data}

        INSTRUCTIONS:
        1. Be concise, friendly, and professional.
        2. If the user asks to perform an action (like "Book a bath for Rex tomorrow"), generate a SMART LINK in Markdown format.
           - Format: `[Action Name](URL)`
           - Example: `[Book Appointment for Rex](/add_appointment?notes=Bath&date=2023-10-10)`
        3. Do NOT try to modify the database directly. You are a read-only assistant that guides users.
        4. If you don't know the answer, suggest checking the Dashboard or Calendar.
        5. Use Markdown for formatting (bold, lists, links).
        """

        chat = model.start_chat(history=[
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": ["Understood. I am Pawfection AI, ready to assist with grooming business tasks using smart links and helpful guidance."]}
        ])

        response = chat.send_message(user_message)

        # Convert Markdown to HTML for safe rendering on frontend
        html_response = markdown.markdown(response.text)

        return jsonify({"response": html_response})

    except Exception as e:
        current_app.logger.error(f"AI Chat Error: {e}", exc_info=True)
        return jsonify({"error": "I'm having trouble connecting to my brain right now. Please try again later."}), 500
