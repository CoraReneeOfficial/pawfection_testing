"""
Simple script to fix duplicate route definitions in app.py.
"""
import re

# Read the app.py file
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the first occurrence and replace it
pattern = r'# Superadmin Configuration Settings route\s+@app\.route\(\'/superadmin/configuration\', methods=\[\'GET\', \'POST\'\]\)\s+def superadmin_configuration\(\):'
replacement = '# Superadmin Global Configuration Settings route\n    @app.route(\'/superadmin/global-configuration\', methods=[\'GET\', \'POST\'])\n    def superadmin_global_config():'

# Apply only to the first occurrence
modified_content = re.sub(pattern, replacement, content, count=1)

# Write the modified content back to app.py
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(modified_content)

print("Route definitions updated successfully.")
