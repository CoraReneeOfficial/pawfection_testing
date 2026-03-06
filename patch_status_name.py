with open('templates/dashboard.html', 'r') as f:
    content = f.read()
content = content.replace("data-status=\"Ready\">Ready</button>", "data-status=\"Ready for Pickup\">Ready for Pickup</button>")
content = content.replace("next_appt.status == 'Ready'", "next_appt.status == 'Ready for Pickup'")
with open('templates/dashboard.html', 'w') as f:
    f.write(content)

with open('appointments/routes.py', 'r') as f:
    content = f.read()
content = content.replace("valid_statuses = ['Checked In', 'In Progress', 'Ready']", "valid_statuses = ['Checked In', 'In Progress', 'Ready for Pickup']")
with open('appointments/routes.py', 'w') as f:
    f.write(content)

with open('notifications/email_utils.py', 'r') as f:
    content = f.read()
content = content.replace("'Ready':", "'Ready for Pickup':")
with open('notifications/email_utils.py', 'w') as f:
    f.write(content)
