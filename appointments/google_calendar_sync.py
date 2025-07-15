import os
import datetime
import json
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
from models import Appointment, Store
from extensions import db
from flask import current_app

# Utility to get Google API credentials from a store
def get_google_credentials(store):
    """Get Google API credentials from a store, with improved error handling and token refresh."""
    if not store or not store.google_token_json:
        current_app.logger.error(f"[GCAL SYNC] No Google token data available for store {getattr(store, 'id', 'unknown')}")
        return None
    
    try:
        # Load token data
        token_data = json.loads(store.google_token_json)
        
        # Check if we have the required token fields
        required_fields = ['refresh_token', 'token_uri', 'client_id', 'client_secret']
        missing_fields = [field for field in required_fields if not token_data.get(field)]
        
        if missing_fields:
            current_app.logger.error(f"[GCAL SYNC] Missing required token fields: {', '.join(missing_fields)}")
            return None
            
        # Get the access token - could be stored as 'token' or 'access_token'
        access_token = token_data.get('token') or token_data.get('access_token')
        
        # Create credentials object
        creds = Credentials(
            token=access_token,
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_data.get('client_id') or os.environ.get('GOOGLE_CLIENT_ID'),
            client_secret=token_data.get('client_secret') or os.environ.get('GOOGLE_CLIENT_SECRET'),
            scopes=[
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.readonly",
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile"
            ]
        )
        
        # Check if token is expired and needs refresh
        if creds.expired:
            current_app.logger.info(f"[GCAL SYNC] Token expired for store {store.id}, attempting refresh")
            try:
                creds.refresh(Request())
                
                # Update the stored token
                new_token_data = {
                    'token': creds.token,
                    'refresh_token': creds.refresh_token,
                    'token_uri': creds.token_uri,
                    'client_id': creds.client_id,
                    'client_secret': creds.client_secret,
                    'scopes': creds.scopes
                }
                store.google_token_json = json.dumps(new_token_data)
                db.session.add(store)
                db.session.commit()
                current_app.logger.info(f"[GCAL SYNC] Successfully refreshed and updated token for store {store.id}")
            except Exception as e:
                current_app.logger.error(f"[GCAL SYNC] Failed to refresh token: {e}")
                return None
        
        return creds
        
    except Exception as e:
        current_app.logger.error(f"[GCAL SYNC] Error creating Google credentials: {e}", exc_info=True)
        return None

# Poll Google Calendar for changed/deleted events and sync local DB
# sync_token should be stored and updated for each store/calendar

def poll_and_sync_deleted_events(store, calendar_id, sync_token=None):
    current_app.logger.info(f"[GCAL SYNC] Called poll_and_sync_deleted_events for store_id={store.id}, calendar_id={calendar_id}, sync_token={sync_token}")
    creds = get_google_credentials(store)
    if not creds:
        current_app.logger.warning(f"[GCAL SYNC] No Google credentials for store {store.id}")
        return
    service = build('calendar', 'v3', credentials=creds)
    events_resource = service.events()
    page_token = None
    deleted_event_ids = set()
    new_sync_token = sync_token
    while True:
        current_app.logger.info(f"[GCAL SYNC] Polling Google Calendar: calendarId={calendar_id}, showDeleted=True, singleEvents=True, syncToken={sync_token}, pageToken={page_token}")
        events_result = events_resource.list(
            calendarId=calendar_id,
            showDeleted=True,
            singleEvents=True,
            syncToken=sync_token,
            pageToken=page_token
        ).execute()
        for event in events_result.get('items', []):
            if event.get('status') == 'cancelled':
                deleted_event_ids.add(event['id'])
        page_token = events_result.get('nextPageToken')
        if not page_token:
            new_sync_token = events_result.get('nextSyncToken', sync_token)
            break
    current_app.logger.info(f"[GCAL SYNC] Deleted Google event IDs found: {list(deleted_event_ids)}")
    # Remove deleted events from DB
    if deleted_event_ids:
        appts = Appointment.query.filter(
            Appointment.google_event_id.in_(deleted_event_ids),
            Appointment.store_id == store.id
        ).all()
        if appts:
            for appt in appts:
                current_app.logger.info(f"[GCAL SYNC] Deleting local appointment: id={appt.id}, google_event_id={appt.google_event_id}")
                db.session.delete(appt)
            db.session.commit()
            current_app.logger.info(f"[GCAL SYNC] Deleted {len(appts)} appointments from DB due to Google Calendar deletions.")
        else:
            current_app.logger.info(f"[GCAL SYNC] No local appointments matched deleted Google event IDs.")
    else:
        current_app.logger.info(f"[GCAL SYNC] No deleted Google event IDs found in this sync.")
    current_app.logger.info(f"[GCAL SYNC] Returning new sync token: {new_sync_token}")
    return new_sync_token
