with open('owners/routes.py', 'r') as f:
    content = f.read()

target1 = "text_notifications_enabled = request.form.get('text_notifications_enabled') == 'on'"
replacement1 = """text_notifications_enabled = request.form.get('text_notifications_enabled') == 'on'
        notify_appointment_reminders = request.form.get('notify_appointment_reminders') == 'on'
        notify_status_updates = request.form.get('notify_status_updates') == 'on'
        notify_marketing = request.form.get('notify_marketing') == 'on'"""

if target1 in content:
    content = content.replace(target1, replacement1)

target2 = "email_notifications_enabled=email_notifications_enabled"
replacement2 = """email_notifications_enabled=email_notifications_enabled,
            notify_appointment_reminders=notify_appointment_reminders,
            notify_status_updates=notify_status_updates,
            notify_marketing=notify_marketing"""

if target2 in content:
    content = content.replace(target2, replacement2)

target3 = "owner.email_notifications_enabled = request.form.get('email_notifications_enabled') == 'on'"
replacement3 = """owner.email_notifications_enabled = request.form.get('email_notifications_enabled') == 'on'
        owner.notify_appointment_reminders = request.form.get('notify_appointment_reminders') == 'on'
        owner.notify_status_updates = request.form.get('notify_status_updates') == 'on'
        owner.notify_marketing = request.form.get('notify_marketing') == 'on'"""

if target3 in content:
    content = content.replace(target3, replacement3)

with open('owners/routes.py', 'w') as f:
    f.write(content)
print("owners/routes.py patched")
