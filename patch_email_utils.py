import re

with open('notifications/email_utils.py', 'r') as f:
    content = f.read()

new_function = """
def send_status_update_notification(store, owner, dog, status):
    '''
    Sends an SMS and/or Email notification to the owner about an appointment status change
    (Check-in, In Progress, Ready for Pickup) if they have opted in.
    '''
    logger = logging.getLogger('app.email')

    if not owner.notify_status_updates:
        logger.info(f"Owner {owner.id} opted out of status updates.")
        return

    if not store.user or not store.user.google_token_json:
        logger.error(f"Cannot send status update: Store User {store.id} missing google_token_json")
        return

    creds_data = json.loads(store.user.google_token_json)
    creds = Credentials.from_authorized_user_info(creds_data)
    service = get_google_service('gmail', 'v1', credentials=creds)

    templates = {
        'Checked In': ('sms_check_in.txt', 'email_check_in.html', 'Check-in Update'),
        'In Progress': ('sms_in_progress.txt', 'email_in_progress.html', 'Groom In Progress'),
        'Ready': ('sms_ready.txt', 'email_ready.html', 'Ready for Pickup!')
    }

    if status not in templates:
        return

    sms_tpl, email_tpl, subject = templates[status]

    # 1. Send SMS
    if owner.text_notifications_enabled and owner.phone_number and owner.phone_carrier:
        try:
            carrier_email = get_carrier_email(owner.phone_number, owner.phone_carrier)
            sms_body = render_template(f"emails/{sms_tpl}", owner_name=owner.name, dog_name=dog.name, store_name=store.name)

            message = MIMEText(sms_body)
            message['To'] = carrier_email
            message['From'] = f"me"
            message['Subject'] = "Update"

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
            logger.info(f"Status SMS ({status}) sent to {owner.id}")
        except Exception as e:
            logger.error(f"Failed to send Status SMS to {owner.id}: {str(e)}")

    # 2. Send Email
    if owner.email_notifications_enabled and owner.email:
        try:
            email_body = render_template(f"emails/{email_tpl}", owner_name=owner.name, dog_name=dog.name, store_name=store.name)

            message = MIMEText(email_body, 'html')
            message['To'] = owner.email
            message['From'] = f"{store.name} <me>"
            message['Subject'] = f"{dog.name} - {subject}"

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
            logger.info(f"Status Email ({status}) sent to {owner.id}")
        except Exception as e:
            logger.error(f"Failed to send Status Email to {owner.id}: {str(e)}")
"""

content = content + "\n" + new_function

with open('notifications/email_utils.py', 'w') as f:
    f.write(content)
print("email_utils.py patched")
