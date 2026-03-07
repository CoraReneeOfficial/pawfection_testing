with open('appointments/routes.py', 'r') as f:
    content = f.read()

if 'import re' not in content:
    content = "import re\n" + content
    with open('appointments/routes.py', 'w') as f:
        f.write(content)
    print("Added import re to appointments/routes.py")

with open('templates/dashboard.html', 'r') as f:
    content = f.read()

target = "alert(`Status successfully updated to: ${newStatus}`);"
replacement = "alert(`Status successfully updated to: ${newStatus} and notifications sent!`);"

if target in content:
    content = content.replace(target, replacement)
    with open('templates/dashboard.html', 'w') as f:
        f.write(content)
    print("Updated alert message in dashboard.html")
