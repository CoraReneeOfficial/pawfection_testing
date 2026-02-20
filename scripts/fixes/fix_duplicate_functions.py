import os
"""
Script to fix duplicate superadmin_global_config function definitions in app.py.
"""
import re

# Read the app.py file
with open(os.path.join(os.path.dirname(__file__), '../../app.py'), 'r', encoding='utf-8') as f:
    content = f.read()

# Count occurrences of the function definition
count = content.count('def superadmin_global_config():')
print(f"Found {count} occurrences of 'def superadmin_global_config():'")

# Replace the second occurrence (line ~2170) with a different function name
pattern = r'@app\.route\(\'/superadmin/global-configuration\', methods=\[\'GET\', \'POST\'\]\)\s+def superadmin_global_config\(\):'
replacement = '@app.route(\'/superadmin/global-configuration\', methods=[\'GET\', \'POST\'])\n    def superadmin_global_config_alt():'

# Split the content into parts based on the pattern
parts = re.split(pattern, content)

if len(parts) >= 3:
    # Join with the replacement for the second occurrence
    modified_content = parts[0] + pattern + parts[1] + replacement + ''.join(parts[2:])
    
    # Write the modified content back to app.py
    with open(os.path.join(os.path.dirname(__file__), '../../app.py'), 'w', encoding='utf-8') as f:
        f.write(modified_content)
    
    print("Successfully renamed second function to superadmin_global_config_alt")
else:
    print("Could not find enough occurrences to safely replace")
