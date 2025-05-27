from extensions import db
import datetime
from datetime import timezone

class Store(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    subscription_status = db.Column(db.String(20), default='active', nullable=False)  # e.g., active, trial, unpaid, cancelled
    subscription_ends_at = db.Column(db.DateTime, nullable=True)
    users = db.relationship('User', backref='store', lazy=True)
    owners = db.relationship('Owner', backref='store', lazy=True)
    dogs = db.relationship('Dog', backref='store', lazy=True)
    services = db.relationship('Service', backref='store', lazy=True)
    appointments = db.relationship('Appointment', backref='store', lazy=True)
    google_token_json = db.Column(db.Text, nullable=True)  # Store Google OAuth token as JSON per store
    def set_password(self, password):
        import bcrypt
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    def check_password(self, password):
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    def __repr__(self):
        return f"<Store {self.name} (ID: {self.id})>"

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='groomer', nullable=False)  # 'admin', 'groomer', 'superadmin'
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=True)  # nullable for superadmin
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_groomer = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    picture_filename = db.Column(db.String(200), nullable=True)
    activity_logs = db.relationship('ActivityLog', backref='user', lazy=True)
    created_owners = db.relationship('Owner', backref='creator', lazy='dynamic', foreign_keys='Owner.created_by_user_id')
    created_dogs = db.relationship('Dog', backref='creator', lazy='dynamic', foreign_keys='Dog.created_by_user_id')
    created_services = db.relationship('Service', backref='creator', lazy='dynamic', foreign_keys='Service.created_by_user_id')
    created_appointments = db.relationship('Appointment', backref='creator', lazy='dynamic', foreign_keys='Appointment.created_by_user_id')
    assigned_appointments = db.relationship('Appointment', backref='groomer', lazy='dynamic', foreign_keys='Appointment.groomer_id')
    def set_password(self, password):
        import bcrypt
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    def check_password(self, password):
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    def __repr__(self):
        return f"<User {self.username} (ID: {self.id}, Role: {self.role}, Store: {self.store_id})>"

class Owner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    address = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    dogs = db.relationship('Dog', backref='owner', lazy='joined', cascade="all, delete-orphan")
    def __repr__(self):
        return f"<Owner {self.name} (ID: {self.id})>"

class Dog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    breed = db.Column(db.String(100), nullable=True)
    birthday = db.Column(db.String(10), nullable=True)
    temperament = db.Column(db.Text, nullable=True)
    hair_style_notes = db.Column(db.Text, nullable=True)
    aggression_issues = db.Column(db.Text, nullable=True)
    anxiety_issues = db.Column(db.Text, nullable=True)
    other_notes = db.Column(db.Text, nullable=True)
    picture_filename = db.Column(db.String(200), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('owner.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    appointments = db.relationship('Appointment', backref='dog', lazy='dynamic', cascade="all, delete-orphan", order_by="desc(Appointment.appointment_datetime)")
    def __repr__(self):
        return f"<Dog {self.name} (ID: {self.id}), Owner ID: {self.owner_id}>"

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    base_price = db.Column(db.Float, nullable=False)
    item_type = db.Column(db.String(50), nullable=False, default='service')
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    def __repr__(self):
        return f"<Service {self.name} (ID: {self.id}), Price: {self.base_price}, Type: {self.item_type}>"

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dog_id = db.Column(db.Integer, db.ForeignKey('dog.id'), nullable=False)
    appointment_datetime = db.Column(db.DateTime, nullable=False)
    requested_services_text = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='Scheduled', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    google_event_id = db.Column(db.String(255), nullable=True)
    groomer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    checkout_total_amount = db.Column(db.Float, nullable=True)
    confirmation_email_sent_at = db.Column(db.DateTime, nullable=True)
    reminder_1_sent_at = db.Column(db.DateTime, nullable=True)
    reminder_2_sent_at = db.Column(db.DateTime, nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    def __repr__(self):
        return f"<Appointment ID: {self.id}, Dog ID: {self.dog_id}, DateTime: {self.appointment_datetime}, Status: {self.status}>"

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    details = db.Column(db.Text, nullable=True)
    def __repr__(self):
        return f"<ActivityLog ID: {self.id}, User ID: {self.user_id}, Action: {self.action}>"

# Models will be moved here in Phase 2 