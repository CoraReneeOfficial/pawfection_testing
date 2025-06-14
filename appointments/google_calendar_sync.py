import os
import datetime
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from models import Appointment, Store
from extensions import db
from flask import current_app

# Utility to get Google API credentials from a store
def get_google_credentials(store):
    if not store or not store.google_token_json:
        return None
    creds = Credentials.from_authorized_user_info(store.google_token_json)
    return creds

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
