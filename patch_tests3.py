with open('tests/test_superadmin_db_security.py', 'r') as f:
    content = f.read()

target = """try:
    import cryptography"""

replacement = """import sys
from unittest.mock import MagicMock
try:
    import cryptography"""

content = content.replace(target, replacement)
with open('tests/test_superadmin_db_security.py', 'w') as f:
    f.write(content)
