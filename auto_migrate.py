import os
import subprocess

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), 'migrations')

# Check if migrations directory exists
if not os.path.exists(MIGRATIONS_DIR):
    print('Migrations directory not found. Initializing...')
    subprocess.run(['flask', 'db', 'init'], check=True)
else:
    print('Migrations directory exists.')

# Always run migrate and upgrade
print('Running flask db migrate...')
subprocess.run(['flask', 'db', 'migrate', '--message', 'Auto migration'], check=True)
print('Running flask db upgrade...')
subprocess.run(['flask', 'db', 'upgrade'], check=True)
print('Migration complete.') 