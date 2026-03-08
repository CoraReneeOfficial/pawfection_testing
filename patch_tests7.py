with open('tests/test_ci_health.py', 'r') as f:
    content = f.read()

target = """try:
    import authlib
except ImportError:
    sys.modules['authlib'] = MagicMock()
    sys.modules['authlib.integrations'] = MagicMock()
    sys.modules['authlib.integrations.flask_client'] = MagicMock()"""

replacement = """try:
    import authlib
except ImportError:
    sys.modules['authlib'] = MagicMock()
    sys.modules['authlib.integrations'] = MagicMock()
    sys.modules['authlib.integrations.flask_client'] = MagicMock()

try:
    import flask_wtf
    import flask_wtf.file
except ImportError:
    sys.modules['flask_wtf'] = MagicMock()
    sys.modules['flask_wtf.file'] = MagicMock()

try:
    import werkzeug.middleware
    import werkzeug.middleware.proxy_fix
except ImportError:
    sys.modules['werkzeug.middleware'] = MagicMock()
    sys.modules['werkzeug.middleware.proxy_fix'] = MagicMock()"""

content = content.replace(target, replacement)
with open('tests/test_ci_health.py', 'w') as f:
    f.write(content)
