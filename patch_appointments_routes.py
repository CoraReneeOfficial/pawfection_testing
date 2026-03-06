with open('appointments/routes.py', 'r') as f:
    content = f.read()

target = "send_appointment_cancelled_email, send_receipt_notification"
replacement = "send_appointment_cancelled_email, send_receipt_notification, send_status_update_notification"

if target in content:
    content = content.replace(target, replacement)

new_route = """
@appointments_bp.route('/api/appointments/<int:appointment_id>/status', methods=['POST'])
@subscription_required
def api_update_appointment_status(appointment_id):
    if 'store_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    store_id = session['store_id']
    appt = Appointment.query.filter_by(id=appointment_id, store_id=store_id).first()
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404

    data = request.get_json()
    new_status = data.get('status')

    valid_statuses = ['Checked In', 'In Progress', 'Ready']
    if new_status not in valid_statuses:
        return jsonify({'error': 'Invalid status'}), 400

    appt.status = new_status
    db.session.commit()

    store = Store.query.get(store_id)
    owner = appt.dog.owner

    try:
        # Sync to Google Calendar
        if store and store.user and store.user.google_token_json and appt.google_event_id:
            creds_data = json.loads(store.user.google_token_json)
            creds = Credentials.from_authorized_user_info(creds_data)
            service = get_google_service('calendar', 'v3', credentials=creds)

            event = service.events().get(calendarId=store.user.google_calendar_id, eventId=appt.google_event_id).execute()
            event['description'] = f"Status: {new_status}\\n" + event.get('description', '')
            service.events().update(calendarId=store.user.google_calendar_id, eventId=appt.google_event_id, body=event).execute()
    except Exception as e:
        current_app.logger.error(f"Error syncing status update to Google Calendar: {e}")

    try:
        # Send notifications
        send_status_update_notification(store, owner, appt.dog, new_status)
    except Exception as e:
        current_app.logger.error(f"Error sending status update notification: {e}")

    return jsonify({'success': True, 'status': new_status})
"""

content = content + "\n" + new_route

with open('appointments/routes.py', 'w') as f:
    f.write(content)
print("appointments/routes.py patched")
