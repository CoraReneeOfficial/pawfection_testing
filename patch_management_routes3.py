import re

with open('management/routes.py', 'r') as f:
    content = f.read()

target_add2 = """        new_user = User(username=username, is_admin=is_admin, is_groomer=is_groomer, store_id=store_id, security_question=security_question, email=email, commission_percentage=commission_percentage)  # Assign store_id, email, commission"""

replacement_add2 = """        new_user = User(username=username, is_admin=is_admin, is_groomer=is_groomer, store_id=store_id, security_question=security_question, email=email, commission_type=commission_type, commission_amount=commission_amount, commission_recipient_id=commission_recipient_id)  # Assign store_id, email, commission"""
content = content.replace(target_add2, replacement_add2)

with open('management/routes.py', 'w') as f:
    f.write(content)
