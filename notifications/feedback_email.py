import os
import json
import logging
import base64
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.credentials import Credentials
from appointments.google_calendar_sync import get_google_service
from models import User

def send_feedback_email(sender_email, sender_name, category, message_body, browser_info):
    """
    Sends a feedback email using the superadmin's Google OAuth credentials.
    """
    logger = logging.getLogger('app.email')

    superadmin = User.query.filter_by(role='superadmin').filter(User.google_token_json != None).first()

    if not superadmin:
        logger.error("No superadmin found with connected Google account. Cannot send feedback email.")
        return False

    try:
        token_data = json.loads(superadmin.google_token_json)

        client_id = token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID')
        client_secret = token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET')

        credentials = Credentials(
            token=token_data.get('token') or token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=client_id,
            client_secret=client_secret,
            scopes=token_data.get('scopes') if 'scopes' in token_data else token_data.get('scope', '').split()
        )

        service = get_google_service('gmail', 'v1', credentials=credentials)
        if not service:
            logger.error("Failed to build Gmail service for superadmin")
            return False

        msg = MIMEMultipart()
        msg['To'] = "pawfection.grooming.solutions@gmail.com"
        msg['Subject'] = "USER FEEDBACK!!!"
        msg['Reply-To'] = sender_email

        safe_sender_name = html.escape(sender_name or '')
        safe_sender_email = html.escape(sender_email or '')
        safe_category = html.escape(category or '')
        safe_message = html.escape(message_body or '').replace('\n', '<br>')
        safe_browser_info = html.escape(browser_info or '')

        email_content = f"""
        <html>
        <body>
            <h2>New Feedback/Report</h2>
            <p><strong>From:</strong> {safe_sender_name} ({safe_sender_email})</p>
            <p><strong>Category:</strong> {safe_category}</p>
            <br>
            <h3>Message:</h3>
            <p>{safe_message}</p>
            <br>
            <hr>
            <h4>System Info:</h4>
            <p style="color: #666; font-size: 0.9em;">{safe_browser_info}</p>
        </body>
        </html>
        """

        msg.attach(MIMEText(email_content, 'html'))
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')

        service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
        logger.info("Feedback email sent successfully.")
        return True

    except Exception as e:
        logger.error(f"Error sending feedback email: {e}")
        return False
