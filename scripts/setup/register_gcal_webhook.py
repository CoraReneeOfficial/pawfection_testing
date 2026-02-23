import os
import sys
import json
import uuid
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Import your app and models
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from app import create_app
from appointments.google_calendar_sync import get_google_service
from models import db, Store

WEBHOOK_URL = 'https://f90f-71-90-228-243.ngrok-free.app/google_calendar/webhook'  # Set to your public webhook endpoint

def register_webhook_for_store(store):
    if isinstance(store.google_token_json, str):
        token_json = json.loads(store.google_token_json)
    else:
        token_json = store.google_token_json
    creds = Credentials.from_authorized_user_info(token_json)
    service = get_google_service('calendar', 'v3', credentials=creds)
    if not service:
        print(f'Failed to build service for store {store.id}')
        return

    calendar_id = store.google_calendar_id
    channel_id = f'pawfection-calendar-channel-{store.id}-{uuid.uuid4().hex[:8]}'
    token = calendar_id  # Use calendar_id as the token for store lookup

    body = {
        'id': channel_id,
        'type': 'web_hook',
        'address': WEBHOOK_URL,
        'token': token,
    }
    response = service.events().watch(calendarId=calendar_id, body=body).execute()
    print(f'Webhook registered for store {store.id} ({store.name})!')
    print('Resource ID:', response.get('resourceId'))
    print('Expiration:', response.get('expiration'))

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        stores = Store.query.filter(
            Store.google_calendar_id.isnot(None),
            Store.google_token_json.isnot(None)
        ).all()
        print(f'Found {len(stores)} store(s) with Google Calendar integration.')
        for store in stores:
            try:
                register_webhook_for_store(store)
            except Exception as e:
                print(f'Failed for store {store.id} ({store.name}): {e}')
