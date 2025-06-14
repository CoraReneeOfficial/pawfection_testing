import os
import json
import datetime
import pytz
from flask import render_template, current_app
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText

def send_appointment_confirmation_email(store, owner, dog, appointment, groomer=None, services_text=None):
    """
    Sends an appointment confirmation email to the owner using the store's Gmail API credentials.
    """
    current_app.logger.info(f"[EMAIL DEBUG] Called send_appointment_confirmation_email for owner: {getattr(owner, 'name', None)}, email: {getattr(owner, 'email', None)}, store: {getattr(store, 'id', None)}")
    if not owner.email:
        current_app.logger.warning(f"[EMAIL DEBUG] No email for owner {getattr(owner, 'name', None)}, skipping confirmation email.")
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
        service = build('gmail', 'v1', credentials=credentials)
        business_name = store.name if hasattr(store, 'name') and store.name else 'Pawfection Grooming'
        store_tz_str = getattr(store, 'timezone', None) or 'UTC'
        try:
            BUSINESS_TIMEZONE = pytz.timezone(store_tz_str)
        except Exception:
            BUSINESS_TIMEZONE = pytz.UTC
        appointment_datetime_local = appointment.appointment_datetime.replace(tzinfo=datetime.timezone.utc).astimezone(BUSINESS_TIMEZONE)
        groomer_name = groomer.username if groomer else None
        html_body = render_template('email/appointment_confirmation.html',
            owner_name=owner.name,
            dog_name=dog.name,
            business_name=business_name,
            appointment_datetime_local=appointment_datetime_local,
            services_text=services_text,
            groomer_name=groomer_name,
            BUSINESS_TIMEZONE_NAME=store_tz_str,
            now=datetime.datetime.now,
            contact_address=getattr(store, 'address', None),
            contact_phone=getattr(store, 'phone', None),
            contact_email=getattr(store, 'email', None)
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
        service = build('gmail', 'v1', credentials=credentials)
        business_name = store.name if hasattr(store, 'name') and store.name else 'Pawfection Grooming'
        store_tz_str = getattr(store, 'timezone', None) or 'UTC'
        try:
            BUSINESS_TIMEZONE = pytz.timezone(store_tz_str)
        except Exception:
            BUSINESS_TIMEZONE = pytz.UTC
        appointment_datetime_local = appointment.appointment_datetime.replace(tzinfo=datetime.timezone.utc).astimezone(BUSINESS_TIMEZONE)
        groomer_name = groomer.username if groomer else None
        html_body = render_template('email/appointment_edited.html',
            owner_name=owner.name,
            dog_name=dog.name,
            business_name=business_name,
            appointment_datetime_local=appointment_datetime_local,
            services_text=services_text,
            groomer_name=groomer_name,
            BUSINESS_TIMEZONE_NAME=store_tz_str,
            now=datetime.datetime.now,
            contact_address=getattr(store, 'address', None),
            contact_phone=getattr(store, 'phone', None),
            contact_email=getattr(store, 'email', None)
        )
        subject = f"Appointment Updated for {dog.name} at {business_name}"
        message = MIMEText(html_body, 'html')
        message['to'] = owner.email
        message['from'] = token_data.get('sender_email', owner.email) if token_data.get('sender_email') else owner.email
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_message = {'raw': raw}
        service.users().messages().send(userId='me', body=send_message).execute()
        current_app.logger.info(f"Sent appointment edited email to {owner.email}")
        return True
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
        service = build('gmail', 'v1', credentials=credentials)
        business_name = store.name if hasattr(store, 'name') and store.name else 'Pawfection Grooming'
        store_tz_str = getattr(store, 'timezone', None) or 'UTC'
        try:
            BUSINESS_TIMEZONE = pytz.timezone(store_tz_str)
        except Exception:
            BUSINESS_TIMEZONE = pytz.UTC
        appointment_datetime_local = appointment.appointment_datetime.replace(tzinfo=datetime.timezone.utc).astimezone(BUSINESS_TIMEZONE)
        groomer_name = groomer.username if groomer else None
        html_body = render_template('email/appointment_cancelled.html',
            owner_name=owner.name,
            dog_name=dog.name,
            business_name=business_name,
            appointment_datetime_local=appointment_datetime_local,
            services_text=services_text,
            groomer_name=groomer_name,
            BUSINESS_TIMEZONE_NAME=store_tz_str,
            now=datetime.datetime.now,
            contact_address=getattr(store, 'address', None),
            contact_phone=getattr(store, 'phone', None),
            contact_email=getattr(store, 'email', None)
        )
        subject = f"Appointment Cancelled for {dog.name} at {business_name}"
        message = MIMEText(html_body, 'html')
        message['to'] = owner.email
        message['from'] = token_data.get('sender_email', owner.email) if token_data.get('sender_email') else owner.email
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_message = {'raw': raw}
        service.users().messages().send(userId='me', body=send_message).execute()
        current_app.logger.info(f"Sent appointment cancelled email to {owner.email}")
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send appointment cancelled email: {e}", exc_info=True)
        return False 