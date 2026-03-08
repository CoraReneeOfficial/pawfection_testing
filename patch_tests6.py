with open('tests/test_ci_health.py', 'r') as f:
    content = f.read()

target = """try:
    import flask_wtf
except ImportError:
    sys.modules['flask_wtf'] = MagicMock()
    sys.modules['flask_wtf.file'] = MagicMock()"""

replacement = """try:
    import flask_wtf
    import flask_wtf.file
except ImportError:
    sys.modules['flask_wtf'] = MagicMock()
    sys.modules['flask_wtf.file'] = MagicMock()"""

content = content.replace(target, replacement)
with open('tests/test_ci_health.py', 'w') as f:
    f.write(content)
