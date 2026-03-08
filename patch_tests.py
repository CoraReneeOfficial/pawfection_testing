with open('tests/test_ci_health.py', 'r') as f:
    content = f.read()

target = """# Ensure DATABASE_URL doesn't trigger postgres connection during create_app
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']"""

replacement = """# Ensure DATABASE_URL doesn't trigger postgres connection during create_app
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

try:
    import stripe
except ImportError:
    sys.modules['stripe'] = MagicMock()
"""

content = content.replace(target, replacement)

target2 = """        # Patch the migration script to do nothing to avoid side effects on the file system
        self.migrate_patcher = patch('app.migrate_add_remind_at_to_notification')
        self.mock_migrate = self.migrate_patcher.start()"""

replacement2 = """        # Patch the migration script to do nothing to avoid side effects on the file system
        self.migrate_patcher = patch('app.migrate_add_remind_at_to_notification')
        self.mock_migrate = self.migrate_patcher.start()
        self.migrate_patcher2 = patch('app.migrate_add_notification_prefs')
        self.mock_migrate2 = self.migrate_patcher2.start()"""

content = content.replace(target2, replacement2)

target3 = """        self.migrate_patcher.stop()"""
replacement3 = """        self.migrate_patcher.stop()
        self.migrate_patcher2.stop()"""
content = content.replace(target3, replacement3)

with open('tests/test_ci_health.py', 'w') as f:
    f.write(content)
