"""
Comprehensive script to fix all duplicate route definitions in app.py.
"""
import re

def find_duplicate_endpoints(content):
    """Find all route definitions and check for duplicates."""
    # Extract all route definitions
    route_pattern = r'@app\.route\([\'"]([^\'"]+)[\'"]'
    routes = re.findall(route_pattern, content)
    
    # Find duplicates
    seen = set()
    duplicates = set()
    for route in routes:
        if route in seen:
            duplicates.add(route)
        else:
            seen.add(route)
    
    return duplicates

def fix_duplicate_routes(content):
    """Fix all duplicate route definitions."""
    # First, find all duplicates
    duplicates = find_duplicate_endpoints(content)
    print(f"Found {len(duplicates)} duplicate routes: {duplicates}")
    
    modified_content = content
    
    # For each duplicate, fix the first occurrence
    for route in duplicates:
        # Escape for regex
        escaped_route = route.replace('/', '\\/')
        
        # Find the first occurrence of this route
        pattern = f'@app\\.route\\([\'"]{escaped_route}[\'"].*?\\)\\s+def ([a-zA-Z0-9_]+)\\(.*?\\):'
        match = re.search(pattern, modified_content, re.DOTALL)
        
        if match:
            # Get the function name
            func_name = match.group(1)
            print(f"Fixing duplicate route: {route} with function {func_name}")
            
            # Create a modified route and function name
            modified_route = f"{route}-alt"
            modified_func = f"{func_name}_alt"
            
            # Replace the first occurrence
            replacement = f'@app.route("{modified_route}"\\1) def {modified_func}('
            modified_content = re.sub(
                f'@app\\.route\\([\'"]{escaped_route}[\'"]\\1\\)\\s+def {func_name}\\(',
                replacement,
                modified_content,
                count=1
            )
            
            print(f"  - Changed to: {modified_route} with function {modified_func}")
    
    return modified_content

# Read the app.py file
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
except UnicodeDecodeError:
    # Try with a different encoding if UTF-8 fails
    with open('app.py', 'r', encoding='latin1') as f:
        content = f.read()

# Specifically fix the superadmin_configuration route first
config_pattern = r'# Superadmin Configuration Settings route\s+@app\.route\(\'\/superadmin\/configuration\', methods=\[\'GET\', \'POST\'\]\)\s+def superadmin_configuration\(\):'
config_replacement = '# Superadmin Global Configuration Settings route\n    @app.route(\'/superadmin/global-configuration\', methods=[\'GET\', \'POST\'])\n    def superadmin_global_config():'

# Apply to the first occurrence
modified_content = re.sub(config_pattern, config_replacement, content, count=1)

# Now look for and fix any other duplicate routes
#modified_content = fix_duplicate_routes(modified_content)

# Write the modified content back to app.py
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(modified_content)

print("Route definitions updated successfully.")
