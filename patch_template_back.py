import re

with open("templates/superadmin_dashboard.html", "r") as f:
    text = f.read()

# Only patch the log variables
text = text.replace("{{ log.username }}", "{{ log.user.username if log.user else 'Unknown User' }}")
text = text.replace("{{ log.store_name }}", "{{ log.store.name if log.store else 'Unknown Store' }}")

with open("templates/superadmin_dashboard.html", "w") as f:
    f.write(text)
