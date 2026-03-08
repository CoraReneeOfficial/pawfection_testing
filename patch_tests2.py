with open('tests/test_superadmin_db_security.py', 'r') as f:
    content = f.read()

target = """try:
    import authlib
except ImportError:
    sys.modules['authlib'] = MagicMock()
    sys.modules['authlib.integrations'] = MagicMock()
    sys.modules['authlib.integrations.flask_client'] = MagicMock()"""

replacement = """try:
    import cryptography
except ImportError:
    sys.modules['cryptography'] = MagicMock()
    sys.modules['cryptography.x509'] = MagicMock()
    sys.modules['cryptography.hazmat'] = MagicMock()
    sys.modules['cryptography.hazmat.backends'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.serialization'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.asymmetric'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.asymmetric.rsa'] = MagicMock()
    sys.modules['cryptography.hazmat.primitives.asymmetric.ec'] = MagicMock()

try:
    import authlib
except ImportError:
    sys.modules['authlib'] = MagicMock()
    sys.modules['authlib.integrations'] = MagicMock()
    sys.modules['authlib.integrations.flask_client'] = MagicMock()
    sys.modules['authlib.jose'] = MagicMock()
    sys.modules['authlib.jose.rfc7517'] = MagicMock()
    sys.modules['authlib.jose.rfc7518'] = MagicMock()"""

content = content.replace(target, replacement)

with open('tests/test_superadmin_db_security.py', 'w') as f:
    f.write(content)
