Pawfection Grooming Solutions
A modular, production-ready Flask web application for managing a dog grooming business. Features include appointment scheduling, owner and dog management, user authentication, admin dashboard, Google Calendar/Gmail integration, and more.

Features
User authentication (admin/groomer roles)

Owner and dog management

Appointment scheduling and calendar view

File uploads for dog and user pictures

Admin dashboard for user/service management, reports, and notifications

Google Calendar and Gmail API integration

Modular codebase using Flask blueprints

Activity logging and error handling

Project Structure
pawfection_testing/
├── .gitignore
├── app.py
├── Dockerfile.dockerfile
├── extensions.py
├── grooming_business_v2.db
├── models.py
├── notification_settings.json
├── pawfection_testing.zip
├── Procfile
├── README.md
├── requirements.txt
├── reset_db.py
├── runtime.txt
├── utils.py
│
├── appointments/         # Appointments blueprint
│     ├── routes.py
│     ├── __init__.py
│     └── __pycache__/
│
├── auth/                 # Authentication blueprint
│     ├── routes.py
│     ├── __init__.py
│     └── __pycache__/
│
├── dogs/                 # Dogs blueprint
│     ├── routes.py
│     ├── __init__.py
│     └── __pycache__/
│
├── management/           # Admin/management blueprint
│     ├── routes.py
│     ├── __init__.py
│     └── __pycache__/
│
├── owners/               # Owners blueprint
│     ├── routes.py
│     ├── __init__.py
│     └── __pycache__/
│
├── static/               # Static files (CSS, images, uploads)
│     ├── style.css
│     │
│     ├── images/
│     │      └── logo.png
│     │
│     └── uploads/
│
├── templates/            # Jinja2 templates
│     ├── add_appointment.html
│     ├── add_dog.html
│     ├── add_owner.html
│     ├── base.html
│     ├── calendar.html
│     ├── checkout.html
│     ├── dashboard.html
│     ├── directory.html
│     ├── dog_profile.html
│     ├── edit_appointment.html
│     ├── edit_dog.html
│     ├── edit_owner.html
│     ├── home_page.html
│     ├── home_page_old.html
│     ├── initial_setup.html
│     ├── login.html
│     ├── logs.html
│     ├── management.html
│     ├── manage_notifications.html
│     ├── manage_services.html
│     ├── manage_users.html
│     ├── owner_profile.html
│     ├── placeholder.html
│     ├── privacy_policy.html
│     ├── reports_form.html
│     ├── report_display.html
│     ├── service_form.html
│     ├── store_login.html
│     ├── store_register.html
│     ├── superadmin_dashboard.html
│     ├── superadmin_login.html
│     ├── superadmin_tools.html
│     ├── user_agreement.html
│     ├── user_form.html
│     │
│     ├── email/
│     │      └── appointment_confirmation.html
│     │
│     └── errors/
│          ├── 403.html
│          ├── 404.html
│          └── 500.html
│
├── uploads/              # Uploaded files (persistent)
└── __pycache__/

Setup & Installation
Clone the repository:

git clone <repo-url>
cd pawfection_testing

Create a virtual environment and activate it:

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

Install dependencies:

pip install -r requirements.txt

Set environment variables (optional for dev):

FLASK_SECRET_KEY (recommended)

GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI (for Google integration)

BUSINESS_TIMEZONE (default: America/New_York)

Run the app locally:

flask run
# or
python app.py

Environment Variables
FLASK_SECRET_KEY: Secret key for Flask sessions

GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI: For Google Calendar/Gmail API

BUSINESS_TIMEZONE: Timezone for appointments (default: America/New_York)

PERSISTENT_DATA_DIR: (optional) Custom data directory for DB/uploads

Running in Production
Use the provided Procfile for deployment (e.g., Railway, Heroku, etc.)

The app uses the app factory pattern (create_app() in app.py)

Ensure all environment variables are set in your deployment environment

Manual Testing Checklist
[ ] Initial setup: Create first admin user

[ ] Login/Logout: Test authentication flows

[ ] Owner management: Add, edit, view, delete owners

[ ] Dog management: Add, edit, view, delete dogs (with picture upload)

[ ] Appointment management: Add, edit, view, delete appointments

[ ] Calendar view: Check calendar and event details

[ ] Checkout: Complete appointment checkout and verify totals

[ ] Admin dashboard: Manage users, services, reports, notifications

[ ] File uploads: Upload and replace dog/user pictures

[ ] Google integration: Connect Google account, sync calendar/events

[ ] Error handling: Trigger and verify 403/404/500 error pages

[ ] Static files: CSS, images, and uploads load correctly

Contributing
Pull requests and suggestions are welcome! Please open an issue or submit a PR.

License
MIT License