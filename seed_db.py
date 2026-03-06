import os
import datetime
import bcrypt
import pytz
import app
from extensions import db
from models import Store, User, Owner, Dog, Appointment, Service
from datetime import timezone

def seed():
    my_app = app.create_app()
    with my_app.app_context():
        # Clear existing data
        db.drop_all()
        db.create_all()

        pwd = bcrypt.hashpw("password123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        store = Store(
            name='Test Store',
            username='teststore',
            password_hash=pwd,
            subscription_status='active',
            subscription_ends_at=datetime.datetime.now(timezone.utc) + datetime.timedelta(days=30)
        )
        db.session.add(store)
        db.session.commit()

        admin = User(username='admin', password_hash=pwd, is_admin=True, store_id=store.id)
        groomer = User(username='groomer', password_hash=pwd, is_admin=False, store_id=store.id)
        db.session.add_all([admin, groomer])
        db.session.commit()

        owner = Owner(name='Test Owner', phone_number='1234567890', email='test@test.com', store_id=store.id, notify_status_updates=True)
        db.session.add(owner)
        db.session.commit()

        dog = Dog(name='Fido', breed='Poodle', owner_id=owner.id, store_id=store.id)
        db.session.add(dog)
        db.session.commit()

        # Create an appointment for TODAY so it shows up in "Up Next" on the dashboard
        tz = pytz.timezone('UTC')
        now = datetime.datetime.now(tz)
        # Schedule it a little bit in the future so it's "next"
        appt_time = now + datetime.timedelta(minutes=30)

        appt = Appointment(
            store_id=store.id,
            dog_id=dog.id,
            appointment_datetime=appt_time,
            status='Scheduled',
            groomer_id=groomer.id,
            created_by_user_id=admin.id
        )
        db.session.add(appt)
        db.session.commit()

        print("Database seeded successfully")

if __name__ == '__main__':
    seed()
