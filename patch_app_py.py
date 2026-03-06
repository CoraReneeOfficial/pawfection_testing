with open('app.py', 'r') as f:
    content = f.read()

target = "import migrate_add_remind_at_to_notification"
replacement = """import migrate_add_remind_at_to_notification
import migrate_add_notification_prefs"""

if target in content:
    content = content.replace(target, replacement)
else:
    content = content.replace("import os", "import os\nimport migrate_add_notification_prefs")

target2 = "migrate_add_remind_at_to_notification.migrate_sqlite(DATABASE_PATH)"
replacement2 = """migrate_add_remind_at_to_notification.migrate_sqlite(DATABASE_PATH)
                migrate_add_notification_prefs.migrate_sqlite(DATABASE_PATH)"""

target3 = "migrate_add_remind_at_to_notification.migrate_postgres(app.config['SQLALCHEMY_DATABASE_URI'])"
replacement3 = """migrate_add_remind_at_to_notification.migrate_postgres(app.config['SQLALCHEMY_DATABASE_URI'])
                migrate_add_notification_prefs.migrate_postgres(app.config['SQLALCHEMY_DATABASE_URI'])"""

if target2 in content:
    content = content.replace(target2, replacement2)
if target3 in content:
    content = content.replace(target3, replacement3)

with open('app.py', 'w') as f:
    f.write(content)
print("app.py patched")
