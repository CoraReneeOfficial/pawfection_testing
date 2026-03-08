import sys
import os
from unittest.mock import Mock

import builtins
# mock dependencies

class MockException(Exception):
    pass

class MockPsycopg2(Mock):
    Error = MockException

sys.modules['psycopg2'] = MockPsycopg2()
sys.modules['psycopg2.sql'] = Mock()
sys.modules['google'] = Mock()
sys.modules['google.genai'] = Mock()
sys.modules['google.genai.types'] = Mock()
sys.modules['google.oauth2'] = Mock()
sys.modules['google.oauth2.credentials'] = Mock()
sys.modules['google.auth'] = Mock()
sys.modules['google.auth.transport'] = Mock()
sys.modules['google.auth.transport.requests'] = Mock()
sys.modules['googleapiclient'] = Mock()
sys.modules['googleapiclient.discovery'] = Mock()
sys.modules['googleapiclient.errors'] = Mock()
sys.modules['authlib'] = Mock()
sys.modules['authlib.integrations'] = Mock()
sys.modules['authlib.integrations.flask_client'] = Mock()
sys.modules['bcrypt'] = Mock()
sys.modules['fpdf'] = Mock()
sys.modules['ollama'] = Mock()
sys.modules['markdown'] = Mock()

from app import create_app
from extensions import db
from models import Store, User

import os
import app as main_app

if 'DATABASE_URL' in main_app.os.environ:
    del main_app.os.environ['DATABASE_URL']
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

app = create_app()
with app.app_context():
    db.create_all()
    store = Store(name="Test Store", username="test_store")
    db.session.add(store)
    db.session.commit()
    admin = User(username="admin", is_admin=True, store_id=store.id)
    db.session.add(admin)
    db.session.commit()
    groomer = User(username="groomer", is_groomer=True, store_id=store.id, commission_type="dollar", commission_amount=50.0, commission_recipient_id=admin.id)
    db.session.add(groomer)
    db.session.commit()

    print(f"Groomer Commission: {groomer.commission_amount} {groomer.commission_type}")
    print(f"Recipient ID: {groomer.commission_recipient_id}")
    print("SUCCESS")
