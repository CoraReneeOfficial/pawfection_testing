import os
import json
import datetime
import logging
import pytz
from flask import render_template, current_app
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from appointments.google_calendar_sync import get_google_service
import base64
from email.mime.text import MIMEText
from utils import service_names_from_ids
from notifications.carrier_utils import get_carrier_email

def send_appointment_confirmation_email(store, owner, dog, appointment, groomer=None, services_text=None):
    """
    Sends an appointment confirmation email to the owner using the store's Gmail API credentials.
    """
    # Set up a logger specifically for email debugging
    # Using 'app.email' to match the logger name in app.py's configure_logging
    logger = logging.getLogger('app.email')
    logger.setLevel(logging.DEBUG)
    
    logger.info("=== Starting email sending process ===")
    logger.info(f"Function called with: store_id={getattr(store, 'id', 'N/A')}, "
                f"owner_id={getattr(owner, 'id', 'N/A')}, "
                f"dog_id={getattr(dog, 'id', 'N/A')}, "
                f"appointment_id={getattr(appointment, 'id', 'N/A')}")
    
    # Check if owner has an email
    if not hasattr(owner, 'email') or not owner.email:
        error_msg = f"No email found for owner {getattr(owner, 'name', 'Unknown')}. Cannot send confirmation email."
        logger.error(error_msg)
        return False
    
    # Check if store has Google token
    if not store or not hasattr(store, 'google_token_json') or not store.google_token_json:
        error_msg = f"No Google token found for store {getattr(store, 'id', 'Unknown')}. Cannot send email."
        logger.error(error_msg)
        return False
    
    # Resolve service names
    services_names = service_names_from_ids(services_text)

    logger.info(f"Preparing to send email to: {owner.email}")
    logger.debug(f"Store name: {getattr(store, 'name', 'N/A')}")
    logger.debug(f"Owner name: {getattr(owner, 'name', 'N/A')}")
    logger.debug(f"Dog name: {getattr(dog, 'name', 'N/A')}")
    logger.debug(f"Appointment time: {getattr(appointment, 'appointment_datetime', 'N/A')}")
    logger.debug(f"Groomer: {getattr(groomer, 'username', 'Not assigned')}")
    logger.debug(f"Services (IDs): {services_text or 'Not specified'}")
    logger.debug(f"Services (Names): {services_names or 'Not specified'}")
    
    # Check if token is valid JSON
    try:
        token_data = json.loads(store.google_token_json)
        logger.debug("Successfully parsed Google token JSON")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse store's google_token_json: {e}")
        return False
    
    try:
        # Log token data (without sensitive info)
        logger.debug("Token data keys: %s", list(token_data.keys()) if token_data else 'No token data')
        
        SCOPES = [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ]
        
        # Get client ID and secret from environment or token data
        client_id = token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID')
        client_secret = token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET')
        
        logger.debug("Creating credentials with scopes: %s", SCOPES)
        logger.debug("Client ID: %s", '***' + client_id[-4:] if client_id else 'Not found')
        
        credentials = Credentials(
            token=token_data.get('token') or token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES
        )
        
        logger.debug("Building Gmail service")
        service = get_google_service('gmail', 'v1', credentials=credentials)
        if not service:
            logger.error("Failed to build Gmail service")
            return False
        
        # Prepare email content
        business_name = store.name if hasattr(store, 'name') and store.name else 'Pawfection Grooming'
        store_tz_str = getattr(store, 'timezone', None) or 'UTC'
        
        try:
            BUSINESS_TIMEZONE = pytz.timezone(store_tz_str)
            logger.debug("Using timezone: %s", store_tz_str)
        except Exception as e:
            logger.warning("Invalid timezone %s, defaulting to UTC. Error: %s", store_tz_str, str(e))
            BUSINESS_TIMEZONE = pytz.UTC
        
        try:
            appointment_datetime_local = appointment.appointment_datetime.replace(tzinfo=datetime.timezone.utc).astimezone(BUSINESS_TIMEZONE)
            logger.debug("Converted appointment time to local timezone")
        except Exception as e:
            logger.error("Failed to convert appointment time: %s", str(e))
            appointment_datetime_local = appointment.appointment_datetime
        
        groomer_name = groomer.username if groomer else None
        
        # Prepare template context
        template_context = {
            'owner_name': owner.name,
            'dog_name': dog.name,
            'business_name': business_name,
            'appointment_datetime_local': appointment_datetime_local,
            'services_text': services_text,
            'services_names': services_names,
            'groomer_name': groomer_name,
            'BUSINESS_TIMEZONE_NAME': store_tz_str,
            'now': datetime.datetime.now,
            'contact_address': getattr(store, 'address', None),
            'contact_phone': getattr(store, 'phone', None),
            'contact_email': getattr(store, 'email', None)
        }
        
        logger.debug("Rendering email template with context: %s", 
                    {k: v for k, v in template_context.items() if k != 'now'})
        
        html_body = render_template('email/appointment_confirmation.html', **template_context)
        
        if not html_body or len(html_body.strip()) < 50:  # Basic check if template rendered
            logger.error("Rendered email template is suspiciously short or empty")
            
        subject = f"Appointment Confirmation for {dog.name} at {business_name}"
        logger.debug("Email subject: %s", subject)
        
        # Determine sender email
        sender_email = token_data.get('sender_email', owner.email) if token_data.get('sender_email') else owner.email
        
        email_sent = False
        
        # 1. Send to Owner Email if enabled
        if getattr(owner, 'email_notifications_enabled', True) and owner.email:
            try:
                message = MIMEText(html_body, 'html')
                message['to'] = owner.email
                message['from'] = sender_email
                message['subject'] = subject

                logger.debug("Prepared email message. From: %s, To: %s", sender_email, owner.email)

                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                send_message = {'raw': raw}

                logger.debug("Sending email through Gmail API...")
                result = service.users().messages().send(userId='me', body=send_message).execute()

                logger.info("Successfully sent appointment confirmation email. Message ID: %s", result.get('id'))
                logger.info("Email sent to: %s", owner.email)
                email_sent = True
            except Exception as e:
                logger.error(f"Failed to send email to {owner.email}: {e}")

        # 2. Send to SMS Gateway if enabled
        if getattr(owner, 'text_notifications_enabled', True):
            carrier_email = get_carrier_email(owner.phone_number, getattr(owner, 'phone_carrier', None))
            if carrier_email:
                try:
                    # Using the same HTML body for now, but stripped down might be better.
                    # Assuming gateways handle HTML or we should send plain text.
                    # Let's send a simplified version? For now, same body to satisfy "associates... handle".

                    message = MIMEText(html_body, 'html')
                    message['to'] = carrier_email
                    message['from'] = sender_email
                    message['subject'] = subject # Subject is often ignored or becomes part of text

                    logger.debug("Prepared text message. From: %s, To: %s", sender_email, carrier_email)

                    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    send_message = {'raw': raw}

                    service.users().messages().send(userId='me', body=send_message).execute()
                    logger.info("Successfully sent appointment confirmation text to: %s", carrier_email)
                    email_sent = True # Consider success if at least one went through?
                except Exception as e:
                    logger.error(f"Failed to send text to {carrier_email}: {e}")
            else:
                logger.debug("Skipping text notification: No valid carrier email derived.")

        return email_sent
        
    except Exception as e:
        logger.error("Failed to send appointment confirmation email", exc_info=True)
        logger.error("Error details: %s", str(e))
        
        # Log more details about the error
        if hasattr(e, 'content'):
            try:
                error_details = json.loads(e.content)
                logger.error("Error details from Google API: %s", error_details)
            except:
                logger.error("Could not parse error content: %s", e.content)
                
        return False

def send_appointment_edited_email(store, owner, dog, appointment, groomer=None, services_text=None):
    """
    Sends an appointment edited notification email to the owner using the store's Gmail API credentials.
    """
    current_app.logger.info(f"[EMAIL DEBUG] Called send_appointment_edited_email for owner: {getattr(owner, 'name', None)}, email: {getattr(owner, 'email', None)}, store: {getattr(store, 'id', None)}")
    if not owner.email:
        current_app.logger.warning(f"[EMAIL DEBUG] No email for owner {getattr(owner, 'name', None)}, skipping edited email.")
        return False
    if not store or not store.google_token_json:
        current_app.logger.warning(f"[EMAIL DEBUG] No Google token for store {getattr(store, 'id', None)}, cannot send email.")
        return False
    try:
        token_data = json.loads(store.google_token_json)
        SCOPES = [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ]
        credentials = Credentials(
            token=token_data.get('token') or token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
            client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
            scopes=SCOPES
        )
        service = get_google_service('gmail', 'v1', credentials=credentials)
        if not service:
            current_app.logger.error("Failed to build Gmail service")
            return False

        business_name = store.name if hasattr(store, 'name') and store.name else 'Pawfection Grooming'
        store_tz_str = getattr(store, 'timezone', None) or 'UTC'
        try:
            BUSINESS_TIMEZONE = pytz.timezone(store_tz_str)
        except Exception:
            BUSINESS_TIMEZONE = pytz.UTC
        appointment_datetime_local = appointment.appointment_datetime.replace(tzinfo=datetime.timezone.utc).astimezone(BUSINESS_TIMEZONE)
        groomer_name = groomer.username if groomer else None

        # Resolve service names
        services_names = service_names_from_ids(services_text)
        current_app.logger.debug(f"Services (IDs): {services_text}")
        current_app.logger.debug(f"Services (Names): {services_names}")

        html_body = render_template('email/appointment_edited.html',
            owner_name=owner.name,
            dog_name=dog.name,
            business_name=business_name,
            appointment_datetime_local=appointment_datetime_local,
            services_text=services_text,
            services_names=services_names,
            groomer_name=groomer_name,
            BUSINESS_TIMEZONE_NAME=store_tz_str,
            now=datetime.datetime.now,
            contact_address=getattr(store, 'address', None),
            contact_phone=getattr(store, 'phone', None),
            contact_email=getattr(store, 'email', None)
        )
        subject = f"Appointment Updated for {dog.name} at {business_name}"
        sender_email = token_data.get('sender_email', owner.email) if token_data.get('sender_email') else owner.email

        email_sent = False

        # 1. Send to Owner Email if enabled
        if getattr(owner, 'email_notifications_enabled', True) and owner.email:
            try:
                message = MIMEText(html_body, 'html')
                message['to'] = owner.email
                message['from'] = sender_email
                message['subject'] = subject
                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                send_message = {'raw': raw}
                service.users().messages().send(userId='me', body=send_message).execute()
                current_app.logger.info(f"Sent appointment edited email to {owner.email}")
                email_sent = True
            except Exception as e:
                current_app.logger.error(f"Failed to send email to {owner.email}: {e}")

        # 2. Send to SMS Gateway if enabled
        if getattr(owner, 'text_notifications_enabled', True):
            carrier_email = get_carrier_email(owner.phone_number, getattr(owner, 'phone_carrier', None))
            if carrier_email:
                try:
                    message = MIMEText(html_body, 'html')
                    message['to'] = carrier_email
                    message['from'] = sender_email
                    message['subject'] = subject
                    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    send_message = {'raw': raw}
                    service.users().messages().send(userId='me', body=send_message).execute()
                    current_app.logger.info(f"Sent appointment edited text to {carrier_email}")
                    email_sent = True
                except Exception as e:
                    current_app.logger.error(f"Failed to send text to {carrier_email}: {e}")

        return email_sent
    except Exception as e:
        current_app.logger.error(f"Failed to send appointment edited email: {e}", exc_info=True)
        return False

def send_appointment_cancelled_email(store, owner, dog, appointment, groomer=None, services_text=None):
    """
    Sends an appointment cancelled notification email to the owner using the store's Gmail API credentials.
    """
    current_app.logger.info(f"[EMAIL DEBUG] Called send_appointment_cancelled_email for owner: {getattr(owner, 'name', None)}, email: {getattr(owner, 'email', None)}, store: {getattr(store, 'id', None)}")
    if not owner.email:
        current_app.logger.warning(f"[EMAIL DEBUG] No email for owner {getattr(owner, 'name', None)}, skipping cancelled email.")
        return False
    if not store or not store.google_token_json:
        current_app.logger.warning(f"[EMAIL DEBUG] No Google token for store {getattr(store, 'id', None)}, cannot send email.")
        return False
    try:
        token_data = json.loads(store.google_token_json)
        SCOPES = [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ]
        credentials = Credentials(
            token=token_data.get('token') or token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
            client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
            scopes=SCOPES
        )
        service = get_google_service('gmail', 'v1', credentials=credentials)
        if not service:
            current_app.logger.error("Failed to build Gmail service")
            return False

        business_name = store.name if hasattr(store, 'name') and store.name else 'Pawfection Grooming'
        store_tz_str = getattr(store, 'timezone', None) or 'UTC'
        try:
            BUSINESS_TIMEZONE = pytz.timezone(store_tz_str)
        except Exception:
            BUSINESS_TIMEZONE = pytz.UTC
        appointment_datetime_local = appointment.appointment_datetime.replace(tzinfo=datetime.timezone.utc).astimezone(BUSINESS_TIMEZONE)
        groomer_name = groomer.username if groomer else None

        # Resolve service names
        services_names = service_names_from_ids(services_text)
        current_app.logger.debug(f"Services (IDs): {services_text}")
        current_app.logger.debug(f"Services (Names): {services_names}")

        html_body = render_template('email/appointment_cancelled.html',
            owner_name=owner.name,
            dog_name=dog.name,
            business_name=business_name,
            appointment_datetime_local=appointment_datetime_local,
            services_text=services_text,
            services_names=services_names,
            groomer_name=groomer_name,
            BUSINESS_TIMEZONE_NAME=store_tz_str,
            now=datetime.datetime.now,
            contact_address=getattr(store, 'address', None),
            contact_phone=getattr(store, 'phone', None),
            contact_email=getattr(store, 'email', None)
        )
        subject = f"Appointment Cancelled for {dog.name} at {business_name}"
        sender_email = token_data.get('sender_email', owner.email) if token_data.get('sender_email') else owner.email

        email_sent = False

        # 1. Send to Owner Email if enabled
        if getattr(owner, 'email_notifications_enabled', True) and owner.email:
            try:
                message = MIMEText(html_body, 'html')
                message['to'] = owner.email
                message['from'] = sender_email
                message['subject'] = subject
                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                send_message = {'raw': raw}
                service.users().messages().send(userId='me', body=send_message).execute()
                current_app.logger.info(f"Sent appointment cancelled email to {owner.email}")
                email_sent = True
            except Exception as e:
                current_app.logger.error(f"Failed to send email to {owner.email}: {e}")

        # 2. Send to SMS Gateway if enabled
        if getattr(owner, 'text_notifications_enabled', True):
            carrier_email = get_carrier_email(owner.phone_number, getattr(owner, 'phone_carrier', None))
            if carrier_email:
                try:
                    message = MIMEText(html_body, 'html')
                    message['to'] = carrier_email
                    message['from'] = sender_email
                    message['subject'] = subject
                    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    send_message = {'raw': raw}
                    service.users().messages().send(userId='me', body=send_message).execute()
                    current_app.logger.info(f"Sent appointment cancelled text to {carrier_email}")
                    email_sent = True
                except Exception as e:
                    current_app.logger.error(f"Failed to send text to {carrier_email}: {e}")

        return email_sent
    except Exception as e:
        current_app.logger.error(f"Failed to send appointment cancelled email: {e}", exc_info=True)
        return False

def send_receipt_notification(store, owner, receipt_data):
    """
    Sends a receipt notification to the owner using the store's Gmail API credentials.
    Specifically targets text messages (via email-to-text gateways) if enabled,
    and can also send email receipts if enabled.
    """
    logger = logging.getLogger('app.email')

    logger.info(f"Preparing to send receipt notification to owner: {getattr(owner, 'name', 'Unknown')}")

    # Check if store has Google token
    if not store or not hasattr(store, 'google_token_json') or not store.google_token_json:
        logger.warning(f"No Google token found for store {getattr(store, 'id', 'Unknown')}. Cannot send receipt.")
        return False

    try:
        token_data = json.loads(store.google_token_json)
        SCOPES = [
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ]

        credentials = Credentials(
            token=token_data.get('token') or token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
            client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
            scopes=SCOPES
        )

        service = get_google_service('gmail', 'v1', credentials=credentials)
        if not service:
            logger.error("Failed to build Gmail service")
            return False

        # Prepare template context
        # Ensure required fields are present
        context = receipt_data.copy()

        # Ensure store info is in context
        if 'store_name' not in context:
            context['store_name'] = getattr(store, 'name', '')
        if 'store_email' not in context:
            context['store_email'] = getattr(store, 'email', '')
        if 'store_phone' not in context:
            context['store_phone'] = getattr(store, 'phone', '')

        # Ensure 'tip' matches 'tip_amount' if needed
        if 'tip' not in context and 'tip_amount' in context:
            context['tip'] = context['tip_amount']

        # Ensure 'date' matches 'receipt_date' if needed
        if 'date' not in context and 'receipt_date' in context:
            context['date'] = context['receipt_date']

        # Render template
        html_body = render_template('email/receipt_email.html', **context)

        subject = f"Receipt from {context.get('store_name', 'Pawfection')}"
        sender_email = token_data.get('sender_email', getattr(store, 'email', 'me'))

        email_sent = False

        # 1. Send to Owner Email if enabled
        if getattr(owner, 'email_notifications_enabled', True) and getattr(owner, 'email', None):
            try:
                message = MIMEText(html_body, 'html')
                message['to'] = owner.email
                message['from'] = sender_email
                message['subject'] = subject
                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                send_message = {'raw': raw}
                service.users().messages().send(userId='me', body=send_message).execute()
                logger.info(f"Sent receipt email to {owner.email}")
                email_sent = True
            except Exception as e:
                logger.error(f"Failed to send receipt email to {owner.email}: {e}")

        # 2. Send to SMS Gateway if enabled
        if getattr(owner, 'text_notifications_enabled', True):
            carrier_email = get_carrier_email(getattr(owner, 'phone_number', ''), getattr(owner, 'phone_carrier', None))
            if carrier_email:
                try:
                    message = MIMEText(html_body, 'html')
                    message['to'] = carrier_email
                    message['from'] = sender_email
                    message['subject'] = subject
                    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    send_message = {'raw': raw}
                    service.users().messages().send(userId='me', body=send_message).execute()
                    logger.info(f"Sent receipt text to {carrier_email}")
                    email_sent = True
                except Exception as e:
                    logger.error(f"Failed to send receipt text to {carrier_email}: {e}")
            else:
                logger.debug("Skipping text notification: No valid carrier email derived.")

        return email_sent

    except Exception as e:
        logger.error(f"Failed to send receipt notification: {e}", exc_info=True)
        return False
