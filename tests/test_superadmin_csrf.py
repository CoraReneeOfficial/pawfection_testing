import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Prevent database connection attempt in app.py if it tries to load from env
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

from app import create_app, db
from models import User

class TestSuperadminCSRF(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.app.config['WTF_CSRF_CHECK_DEFAULT'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            if not User.query.filter_by(username='admin').first():
                user = User(username='admin', role='superadmin', is_admin=True)
                user.password_hash = 'hash'
                db.session.add(user)
                db.session.commit()

            self.user_id = User.query.filter_by(username='admin').first().id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['is_superadmin'] = True
            sess['_fresh'] = True

    def test_user_permissions_ajax_csrf(self):
        self.login()

        # Missing CSRF in header should fail
        response = self.client.post('/superadmin/user_permissions',
            json={'action': 'update_user_permission', 'user_id': 1, 'permission_id': 'manage_users', 'is_granted': True},
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )

        self.assertEqual(response.status_code, 400)

if __name__ == '__main__':
    unittest.main()
