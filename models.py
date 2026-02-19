from extensions import db
import datetime
from datetime import timezone
from sqlalchemy.orm import declared_attr

class SecurityMixin:
    """
    Mixin for models that require password and security question/answer functionality.
    """
    @declared_attr
    def password_hash(cls):
        return db.Column(db.String(128), nullable=False)

    @declared_attr
    def security_question(cls):
        return db.Column(db.String(255), nullable=True)

    @declared_attr
    def security_answer_hash(cls):
        return db.Column(db.String(128), nullable=True)

    def set_password(self, password):
        """Hashes the given password and stores it."""
        import bcrypt
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        """Checks if the given password matches the stored hash."""
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def set_security_answer(self, answer):
        """Hashes the security answer and stores it."""
        import bcrypt
        if answer:
            self.security_answer_hash = bcrypt.hashpw(answer.lower().encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_security_answer(self, answer):
        """Checks if the given security answer matches the stored hash."""
        import bcrypt
        if not self.security_answer_hash or not answer:
            return False
        return bcrypt.checkpw(answer.lower().encode('utf-8'), self.security_answer_hash.encode('utf-8'))

class Store(SecurityMixin, db.Model):
    """
    Represents a single grooming business store.
    Each store has its own set of users, owners, dogs, services, and appointments.

    New fields added for business management and customization.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False) # Username for store login
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    subscription_status = db.Column(db.String(20), default='inactive', nullable=False)  # e.g., active, trial, unpaid, cancelled; default is 'inactive' so new stores must subscribe
    subscription_ends_at = db.Column(db.DateTime, nullable=True)
    google_token_json = db.Column(db.Text, nullable=True)  # Store Google OAuth token as JSON per store
    google_calendar_id = db.Column(db.String(255), nullable=True)  # Store Google Calendar ID for the store
    address = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    timezone = db.Column(db.String(64), nullable=True)

    # --- New fields for advanced store management ---
    logo_filename = db.Column(db.String(200), nullable=True)  # Logo or profile image filename
    status = db.Column(db.String(20), default='active', nullable=False)  # Store status: active/inactive
    business_hours = db.Column(db.Text, nullable=True)  # JSON/text for business hours
    description = db.Column(db.Text, nullable=True)  # Store description/about
    facebook_url = db.Column(db.String(255), nullable=True)  # Facebook page link
    instagram_url = db.Column(db.String(255), nullable=True)  # Instagram profile link
    website_url = db.Column(db.String(255), nullable=True)  # Store website
    tax_id = db.Column(db.String(100), nullable=True)  # Tax/business ID
    notification_preferences = db.Column(db.Text, nullable=True)  # JSON/text for notification settings
    default_appointment_duration = db.Column(db.Integer, nullable=True)  # Default appointment duration in minutes
    default_appointment_buffer = db.Column(db.Integer, nullable=True)  # Buffer time between appointments in minutes
    payment_settings = db.Column(db.Text, nullable=True)  # JSON/text for payment settings (e.g., Stripe, PayPal)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)  # Soft delete/archive flag
    tax_enabled = db.Column(db.Boolean, default=True, nullable=False)  # Enable/disable taxes for invoices/receipts

    # --- Stripe integration fields ---
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)
    
    # Relationships to other models, ensuring data is linked to the store
    users = db.relationship('User', backref='store', lazy=True)
    owners = db.relationship('Owner', backref='store', lazy=True)
    dogs = db.relationship('Dog', backref='store', lazy=True)
    services = db.relationship('Service', backref='store', lazy=True)
    appointments = db.relationship('Appointment', backref='store', lazy=True)
    activity_logs = db.relationship('ActivityLog', backref='store', lazy=True) # Added relationship for ActivityLog
    
    def __repr__(self):
        return f"<Store {self.name} (ID: {self.id})>"

class User(SecurityMixin, db.Model):
    """
    Represents a user (admin, groomer, or superadmin) within a specific store.
    Superadmins are not tied to a store (store_id=None).
    """
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False) # Username must be unique across all users
    role = db.Column(db.String(20), default='groomer', nullable=False)  # 'admin', 'groomer', 'superadmin'
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=True)  # nullable for superadmin
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_groomer = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    picture_filename = db.Column(db.String(200), nullable=True)
    google_sub = db.Column(db.String(255), unique=True, nullable=True)  # Google unique user ID
    email = db.Column(db.String(255), unique=True, nullable=True)  # Email address

    # Stripe subscription fields
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)
    is_subscribed = db.Column(db.Boolean, default=False, nullable=False)
    
    # Relationships to data created or assigned by this user
    activity_logs = db.relationship('ActivityLog', backref='user', lazy=True)
    created_owners = db.relationship('Owner', backref='creator', lazy='dynamic', foreign_keys='Owner.created_by_user_id')
    created_dogs = db.relationship('Dog', backref='creator', lazy='dynamic', foreign_keys='Dog.created_by_user_id')
    created_services = db.relationship('Service', backref='creator', lazy='dynamic', foreign_keys='Service.created_by_user_id')
    created_appointments = db.relationship('Appointment', backref='creator', lazy='dynamic', foreign_keys='Appointment.created_by_user_id')
    assigned_appointments = db.relationship('Appointment', backref='groomer', lazy='dynamic', foreign_keys='Appointment.groomer_id')

    def __repr__(self):
        return f"<User {self.username} (ID: {self.id}, Role: {self.role}, Store: {self.store_id})>"

    # --- Flask-Login integration ---
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

class Owner(db.Model):
    """
    Represents a dog owner, associated with a specific store.
    Phone number and email are unique per store.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # Unique constraint for phone_number should be combined with store_id in a unique composite index
    phone_number = db.Column(db.String(20), nullable=False)
    # Unique constraint for email should be combined with store_id in a unique composite index
    email = db.Column(db.String(120), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)

    dogs = db.relationship('Dog', backref='owner', lazy='joined', cascade="all, delete-orphan")

    # Composite unique constraints to ensure phone_number and email are unique PER STORE
    __table_args__ = (
        db.UniqueConstraint('phone_number', 'store_id', name='_phone_number_store_uc'),
        db.UniqueConstraint('email', 'store_id', name='_email_store_uc'),
    )

    def __repr__(self):
        return f"<Owner {self.name} (ID: {self.id}), Store ID: {self.store_id}>"

class Dog(db.Model):
    """
    Represents a dog, associated with an owner and a specific store.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    breed = db.Column(db.String(100), nullable=True)
    birthday = db.Column(db.String(10), nullable=True) # Stored as string for flexibility (e.g., "Jan 1, 2020")
    temperament = db.Column(db.Text, nullable=True)
    hair_style_notes = db.Column(db.Text, nullable=True)
    aggression_issues = db.Column(db.Text, nullable=True)
    anxiety_issues = db.Column(db.Text, nullable=True)
    other_notes = db.Column(db.Text, nullable=True)
    vaccines = db.Column(db.Text, nullable=True)
    picture_filename = db.Column(db.String(200), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('owner.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False) # Dog inherits store_id from owner

    appointments = db.relationship('Appointment', backref='dog', lazy='dynamic', cascade="all, delete-orphan", order_by="desc(Appointment.appointment_datetime)")

    def __repr__(self):
        return f"<Dog {self.name} (ID: {self.id}), Owner ID: {self.owner_id}, Store ID: {self.store_id}>"

class Service(db.Model):
    """
    Represents a grooming service or an additional fee, associated with a specific store.
    Name is unique per store.
    """
    id = db.Column(db.Integer, primary_key=True)
    # Unique constraint for name should be combined with store_id in a unique composite index
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    base_price = db.Column(db.Float, nullable=False)
    item_type = db.Column(db.String(50), nullable=False, default='service') # 'service' or 'fee'
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)

    # Composite unique constraint to ensure name is unique PER STORE
    __table_args__ = (
        db.UniqueConstraint('name', 'store_id', name='_name_store_uc'),
    )

    def __repr__(self):
        return f"<Service {self.name} (ID: {self.id}), Price: {self.base_price}, Type: {self.item_type}, Store ID: {self.store_id}>"

class Appointment(db.Model):
    """
    Represents a grooming appointment, associated with a specific dog, groomer, and store.
    """
    id = db.Column(db.Integer, primary_key=True)
    dog_id = db.Column(db.Integer, db.ForeignKey('dog.id'), nullable=False)
    appointment_datetime = db.Column(db.DateTime, nullable=False)
    requested_services_text = db.Column(db.Text, nullable=True) # Comma-separated list of service names
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='Scheduled', nullable=False) # e.g., 'Scheduled', 'Completed', 'Cancelled', 'No Show'
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    google_event_id = db.Column(db.String(255), nullable=True) # ID for Google Calendar event sync
    groomer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Groomer assigned to the appointment
    checkout_total_amount = db.Column(db.Float, nullable=True) # Final amount after checkout
    confirmation_email_sent_at = db.Column(db.DateTime, nullable=True)
    reminder_1_sent_at = db.Column(db.DateTime, nullable=True)
    reminder_2_sent_at = db.Column(db.DateTime, nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False) # Appointment belongs to a store
    details_needed = db.Column(db.Boolean, default=False, nullable=False)  # Flag for missing vital info

    def __repr__(self):
        return f"<Appointment ID: {self.id}, Dog ID: {self.dog_id}, DateTime: {self.appointment_datetime}, Status: {self.status}, Store ID: {self.store_id}>"

class AppointmentRequest(db.Model):
    """
    Represents a customer-submitted appointment request from the public store page.
    Admins can later approve (which will convert it into proper Owner / Dog / Appointment records) or reject.
    """
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    dog_name = db.Column(db.String(100), nullable=True)
    preferred_datetime = db.Column(db.String(100), nullable=True)  # Free-form preferred date/time
    owner_id = db.Column(db.Integer, db.ForeignKey('owner.id'), nullable=True)
    dog_id = db.Column(db.Integer, db.ForeignKey('dog.id'), nullable=True)
    requested_services_text = db.Column(db.Text, nullable=True)  # Comma-separated list of service IDs requested
    groomer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending / approved / rejected
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)

    store = db.relationship('Store', backref='appointment_requests', lazy=True)

    def __repr__(self):
        return f"<ApptRequest {self.customer_name} for store {self.store_id} (status {self.status})>"

class ActivityLog(db.Model):
    """
    Records user actions within the application, associated with a user and a store.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    details = db.Column(db.Text, nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False) # ADDED: Link activity log to a specific store

    def __repr__(self):
        return f"<ActivityLog ID: {self.id}, User ID: {self.user_id}, Action: {self.action}, Store ID: {self.store_id}>"

class Receipt(db.Model):
    """
    Stores a finalized receipt for an appointment, including all itemized data as JSON for future viewing, printing, or emailing.
    """
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('owner.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    receipt_json = db.Column(db.Text, nullable=False)  # All receipt data at time of checkout
    filename = db.Column(db.String(255), nullable=True)  # For PDF or download

    appointment = db.relationship('Appointment', backref='receipt', uselist=False)
    store = db.relationship('Store', backref='receipts')
    owner = db.relationship('Owner', backref='receipts')

    def __repr__(self):
        return f"<Receipt ID: {self.id}, Appt: {self.appointment_id}, Store: {self.store_id}>"

class Notification(db.Model):
    """
    Represents a notification for users, such as appointment requests or appointments needing review.
    """
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Can be null if for all store users
    type = db.Column(db.String(50), nullable=False)  # 'appointment_request', 'appointment_needs_review', etc.
    content = db.Column(db.Text, nullable=False)
    reference_id = db.Column(db.Integer, nullable=True)  # ID of related object (appointment, etc.)
    reference_type = db.Column(db.String(50), nullable=True)  # Type of related object ('appointment', etc.)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(timezone.utc), nullable=False)
    remind_at = db.Column(db.DateTime, nullable=True)
    shown_in_popup = db.Column(db.Boolean, default=False, nullable=False)
    
    # Relationships
    store = db.relationship('Store', backref='notifications')
    user = db.relationship('User', backref='notifications')
    
    def __repr__(self):
        return f"<Notification ID: {self.id}, Type: {self.type}, Read: {self.is_read}, Store: {self.store_id}>"

# Models will be moved here in Phase 2
