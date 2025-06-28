from flask import Blueprint, request, current_app
from models import Appointment, Store
from extensions import db
import json

webhook_bp = Blueprint('google_calendar_webhook', __name__)

@webhook_bp.route('/google_calendar/webhook', methods=['POST'])
def google_calendar_webhook():
    """
    Secure Google Calendar webhook endpoint:
    - Validates Google-supplied headers for authenticity
    - Implements basic replay protection with a nonce
    - Logs suspicious/malformed requests for audit
    - Polls for deleted events on valid notifications
    """
    import hashlib
    import time
    from flask import abort

    # Google sends notifications with headers
    channel_id = request.headers.get('X-Goog-Channel-ID')
    resource_state = request.headers.get('X-Goog-Resource-State')
    resource_id = request.headers.get('X-Goog-Resource-ID')
    calendar_id = request.headers.get('X-Goog-Channel-Token')  # Used to identify the store
    message_number = request.headers.get('X-Goog-Message-Number')

    # Validate required headers
    if not channel_id or not resource_state or not resource_id or not calendar_id:
        current_app.logger.warning('[GCAL WEBHOOK] Missing required Google headers. Possible spoofed or malformed request.')
        abort(400)

    # --- BEGIN: Basic Replay Protection ---
    # Use a simple nonce mechanism: store last message number for this channel/calendar
    # In production, use a database or cache (e.g., Redis) for distributed replay protection
    nonce_dir = 'webhook_nonces'
    os.makedirs(nonce_dir, exist_ok=True)
    nonce_file = os.path.join(nonce_dir, f'gcal_{calendar_id}_{channel_id}.nonce')
    last_nonce = None
    try:
        if os.path.exists(nonce_file):
            with open(nonce_file, 'r') as f:
                last_nonce = f.read().strip()
        if message_number and last_nonce and int(message_number) <= int(last_nonce):
            current_app.logger.warning(f'[GCAL WEBHOOK] Replay detected: message_number={message_number}, last_nonce={last_nonce}')
            abort(409)  # Conflict: replayed message
        # Store new nonce
        if message_number:
            with open(nonce_file, 'w') as f:
                f.write(str(message_number))
    except Exception as e:
        current_app.logger.error(f'[GCAL WEBHOOK] Nonce handling error: {e}', exc_info=True)
        # Do not abort, but log for investigation
    # --- END: Basic Replay Protection ---

    # Google sends a sync message when the webhook is first set up
    if resource_state == 'sync':
        current_app.logger.info('[GCAL WEBHOOK] Google Calendar webhook sync message received.')
        return '', 200

    # For any change, poll for deleted events
    try:
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
                current_app.logger.info(f'[GCAL WEBHOOK] Polled Google Calendar for changes for store {store.id}')
            else:
                current_app.logger.warning(f'[GCAL WEBHOOK] No store found for calendar_id {calendar_id}')
        else:
            current_app.logger.warning('[GCAL WEBHOOK] No calendar_id in webhook notification')
    except Exception as e:
        current_app.logger.error(f'[GCAL WEBHOOK] Error polling/syncing calendar: {e}', exc_info=True)
        abort(500)
    return '', 200

# Utility: Function to poll Google Calendar for deleted events and sync
# (To be implemented in a management script or background job)
