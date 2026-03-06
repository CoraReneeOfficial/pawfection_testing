with open('models.py', 'r') as f:
    content = f.read()

target = "email_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)"
replacement = """email_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Granular notification preferences
    notify_appointment_reminders = db.Column(db.Boolean, default=True, nullable=False)
    notify_status_updates = db.Column(db.Boolean, default=True, nullable=False)
    notify_marketing = db.Column(db.Boolean, default=True, nullable=False)"""

if target in content:
    content = content.replace(target, replacement)
    with open('models.py', 'w') as f:
        f.write(content)
    print("Replaced successfully")
else:
    print("Target not found")
