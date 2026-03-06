with open('templates/add_owner.html', 'r') as f:
    content = f.read()

target = """            <div class="form-group" style="display: flex; align-items: center; gap: 0.5rem;">
                <input type="checkbox" id="email_notifications_enabled" name="email_notifications_enabled" {% if owner.email_notifications_enabled != False %}checked{% endif %}>
                <label for="email_notifications_enabled" style="margin-bottom: 0; font-weight: normal;">Enable Email Notifications</label>
            </div>"""

replacement = """            <div class="form-group" style="display: flex; align-items: center; gap: 0.5rem;">
                <input type="checkbox" id="email_notifications_enabled" name="email_notifications_enabled" {% if owner.email_notifications_enabled != False %}checked{% endif %}>
                <label for="email_notifications_enabled" style="margin-bottom: 0; font-weight: normal;">Enable Email Notifications</label>
            </div>

            <h3 style="margin-top: 1.5rem; margin-bottom: 1rem; border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem;">Notification Preferences</h3>

            <div class="form-group" style="display: flex; align-items: center; gap: 0.5rem;">
                <input type="checkbox" id="notify_appointment_reminders" name="notify_appointment_reminders" {% if owner.notify_appointment_reminders != False %}checked{% endif %}>
                <label for="notify_appointment_reminders" style="margin-bottom: 0; font-weight: normal;">Receive Appointment Reminders</label>
            </div>

            <div class="form-group" style="display: flex; align-items: center; gap: 0.5rem;">
                <input type="checkbox" id="notify_status_updates" name="notify_status_updates" {% if owner.notify_status_updates != False %}checked{% endif %}>
                <label for="notify_status_updates" style="margin-bottom: 0; font-weight: normal;">Receive Grooming Status Updates (Check-in, In Progress, Ready)</label>
            </div>

            <div class="form-group" style="display: flex; align-items: center; gap: 0.5rem;">
                <input type="checkbox" id="notify_marketing" name="notify_marketing" {% if owner.notify_marketing != False %}checked{% endif %}>
                <label for="notify_marketing" style="margin-bottom: 0; font-weight: normal;">Receive Marketing & Special Offers</label>
            </div>"""

if target in content:
    content = content.replace(target, replacement)
    with open('templates/add_owner.html', 'w') as f:
        f.write(content)
    print("templates/add_owner.html patched")

with open('templates/edit_owner.html', 'r') as f:
    content2 = f.read()

if target in content2:
    content2 = content2.replace(target, replacement)
    with open('templates/edit_owner.html', 'w') as f:
        f.write(content2)
    print("templates/edit_owner.html patched")
