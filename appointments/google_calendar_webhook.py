from flask import Blueprint, request, current_app
from models import Appointment, Store
from extensions import db
import json

webhook_bp = Blueprint('google_calendar_webhook', __name__)

@webhook_bp.route('/google_calendar/webhook', methods=['POST'])
def google_calendar_webhook():
    # Google sends notifications with headers
    channel_id = request.headers.get('X-Goog-Channel-ID')
    resource_state = request.headers.get('X-Goog-Resource-State')
    resource_id = request.headers.get('X-Goog-Resource-ID')
    calendar_id = request.headers.get('X-Goog-Channel-Token')  # We'll use this to identify the store

    # Google sends a sync message when the webhook is first set up
    if resource_state == 'sync':
        current_app.logger.info('Google Calendar webhook sync message received.')
        return '', 200

    # For any change, poll for deleted events
    if calendar_id:
        # Find store by calendar_id
        store = Store.query.filter_by(google_calendar_id=calendar_id).first()
        if store:
            # Store sync token in a file (demo only; use DB in production)
            sync_token_file = f'store_{store.id}_gcal_sync_token.txt'
            sync_token = None
            if os.path.exists(sync_token_file):
                with open(sync_token_file, 'r') as f:
                    sync_token = f.read().strip()
            from appointments.google_calendar_sync import poll_and_sync_deleted_events
            new_sync_token = poll_and_sync_deleted_events(store, calendar_id, sync_token)
            if new_sync_token and new_sync_token != sync_token:
                with open(sync_token_file, 'w') as f:
                    f.write(new_sync_token)
            current_app.logger.info(f'Polled Google Calendar for changes for store {store.id}')
        else:
            current_app.logger.warning(f'No store found for calendar_id {calendar_id}')
    else:
        current_app.logger.warning('No calendar_id in webhook notification')
    return '', 200

# Utility: Function to poll Google Calendar for deleted events and sync
# (To be implemented in a management script or background job)
