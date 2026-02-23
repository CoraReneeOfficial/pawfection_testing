
import sys
import os
import time
import datetime
from datetime import timedelta, timezone
import random
import unittest

# Add current directory to path so we can import app
sys.path.append(os.getcwd())

from app import create_app, db
from models import User, Store, Appointment, Dog, Owner

class TestCalendarPerformance(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()

            # Create Store
            self.store = Store(name="Perf Store", subscription_status='active', timezone='America/New_York', username="perfuser", email="perf@example.com")
            self.store.set_password("password")
            db.session.add(self.store)
            db.session.commit()

            # Create User
            self.user = User(username="perfuser", email="perf@example.com", store_id=self.store.id, role='admin')
            self.user.set_password("password")
            db.session.add(self.user)
            db.session.commit()

            # Create Owner and Dog
            self.owner = Owner(name="Perf Owner", email="owner@example.com", phone_number="555-0100", store_id=self.store.id)
            db.session.add(self.owner)
            db.session.flush()

            self.dog = Dog(name="Perf Dog", owner_id=self.owner.id, store_id=self.store.id)
            db.session.add(self.dog)
            db.session.commit()

            # Insert Appointments
            print("Inserting 2000 appointments...")
            appointments = []
            now = datetime.datetime.now(timezone.utc)

            for i in range(1000):
                # Past
                dt = now - timedelta(days=random.randint(1, 730))
                appointments.append(Appointment(
                    dog_id=self.dog.id,
                    store_id=self.store.id,
                    appointment_datetime=dt,
                    status=random.choice(['Completed', 'Cancelled', 'No Show']),
                    created_by_user_id=self.user.id
                ))

                # Future
                dt = now + timedelta(days=random.randint(1, 730))
                appointments.append(Appointment(
                    dog_id=self.dog.id,
                    store_id=self.store.id,
                    appointment_datetime=dt,
                    status='Scheduled',
                    created_by_user_id=self.user.id
                ))

            db.session.bulk_save_objects(appointments)
            db.session.commit()
            print("Appointments inserted.")

            # Store IDs for test use
            self.user_id = self.user.id
            self.store_id = self.store.id

    def test_calendar_load_time(self):
        # Login
        with self.client:
            self.client.post('/login', data={'username': 'perfuser', 'password': 'password'}, follow_redirects=True)

            # Manually set session data to ensure store_id is present
            with self.client.session_transaction() as sess:
                sess['user_id'] = self.user_id
                sess['store_id'] = self.store_id
                sess['_fresh'] = True

            # Measure /calendar load time
            start_time = time.time()
            response = self.client.get('/calendar')
            end_time = time.time()

            print(f"\n/calendar Load Time: {end_time - start_time:.6f} seconds")
            self.assertEqual(response.status_code, 200)

            # Check if content is correct
            self.assertIn(b"Recent & Upcoming Appointments", response.data)
            # We expect some appointments (since we inserted random ones, some should fall in -7 to +30 days)
            # Probability: 37 days out of 730+730=1460 days. ~2.5%. With 2000 appts, expect ~50 appts.
            # So "No appointments found" should NOT be present usually, but let's check for the positive case.
            # Or at least check we don't see the old header "Scheduled Appointments (Managed in App)"
            self.assertNotIn(b"Scheduled Appointments (Managed in App)", response.data)

if __name__ == '__main__':
    unittest.main()
