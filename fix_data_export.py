"""
Fix duplicate superadmin_data_export function names in app.py by renaming the second occurrence.
"""
import re

def fix_duplicate_function():
    try:
        # Read the file content
        with open('app.py', 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Find all occurrences of the function name
        matches = list(re.finditer(r'def superadmin_data_export\(\):', content))
        
        if len(matches) < 2:
            print(f"Found only {len(matches)} occurrences, not enough to fix")
            return False
        
        # Get the position of the second occurrence
        second_match = matches[1]
        start_pos = second_match.start()
        
        # Replace only the second occurrence
        new_content = (
            content[:start_pos] + 
            "def superadmin_data_export_alt():" + 
            content[start_pos + len("def superadmin_data_export():"):]
        )
        
        # Also change the route path for the second occurrence
        route_pattern = r"@app\.route\('/superadmin/data-export', methods=\['GET', 'POST'\]\)"
        route_matches = list(re.finditer(route_pattern, new_content))
        
        if len(route_matches) >= 2:
            second_route = route_matches[1]
            route_start = second_route.start()
            route_end = second_route.end()
            
            new_content = (
                new_content[:route_start] + 
                "@app.route('/superadmin/data-export-alt', methods=['GET', 'POST'])" + 
                new_content[route_end:]
            )
        
        # Write the modified content back
        with open('app.py', 'w', encoding='utf-8') as file:
            file.write(new_content)
        
        print("Successfully fixed duplicate function names")
        return True
    
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    if fix_duplicate_function():
        print("Fix completed successfully")
    else:
        print("Fix failed")
