# Pawfection Grooming Solutions

A modular, production-ready Flask web application for managing a dog grooming business. Features include appointment scheduling, owner and dog management, user authentication, admin dashboard, Google Calendar/Gmail integration, and more.

---

## Features
- User authentication (admin/groomer roles)
- Owner and dog management
- Appointment scheduling and calendar view
- File uploads for dog and user pictures
- Admin dashboard for user/service management, reports, and notifications
- Google Calendar and Gmail API integration
- Modular codebase using Flask blueprints
- Activity logging and error handling

---

## Project Structure
```
pawfection_testing/
├── appointments/         # Appointments blueprint
├── auth/                # Authentication blueprint
├── dogs/                # Dogs blueprint
├── management/          # Admin/management blueprint
├── owners/              # Owners blueprint
├── static/              # Static files (CSS, images, uploads)
├── templates/           # Jinja2 templates
├── uploads/             # Uploaded files (persistent)
├── app.py               # App factory and entry point
├── extensions.py        # Flask extensions (db)
├── models.py            # SQLAlchemy models
├── utils.py             # Shared helper functions
├── requirements.txt     # Python dependencies
├── Procfile             # For deployment (e.g., Railway, Heroku)
├── ...
```

---

## Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd pawfection_testing
   ```

2. **Create a virtual environment and activate it:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set environment variables (optional for dev):**
   - `FLASK_SECRET_KEY` (recommended)
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (for Google integration)
   - `BUSINESS_TIMEZONE` (default: America/New_York)

5. **Run the app locally:**
   ```bash
   flask run
   # or
   python app.py
   ```

---

## Environment Variables
- `FLASK_SECRET_KEY`: Secret key for Flask sessions
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`: For Google Calendar/Gmail API
- `BUSINESS_TIMEZONE`: Timezone for appointments (default: America/New_York)
- `PERSISTENT_DATA_DIR`: (optional) Custom data directory for DB/uploads

---

## Running in Production
- Use the provided `Procfile` for deployment (e.g., Railway, Heroku, etc.)
- The app uses the app factory pattern (`create_app()` in `app.py`)
- Ensure all environment variables are set in your deployment environment

---

## Manual Testing Checklist
- [ ] **Initial setup:** Create first admin user
- [ ] **Login/Logout:** Test authentication flows
- [ ] **Owner management:** Add, edit, view, delete owners
- [ ] **Dog management:** Add, edit, view, delete dogs (with picture upload)
- [ ] **Appointment management:** Add, edit, view, delete appointments
- [ ] **Calendar view:** Check calendar and event details
- [ ] **Checkout:** Complete appointment checkout and verify totals
- [ ] **Admin dashboard:** Manage users, services, reports, notifications
- [ ] **File uploads:** Upload and replace dog/user pictures
- [ ] **Google integration:** Connect Google account, sync calendar/events
- [ ] **Error handling:** Trigger and verify 403/404/500 error pages
- [ ] **Static files:** CSS, images, and uploads load correctly

---

## Contributing
Pull requests and suggestions are welcome! Please open an issue or submit a PR.

## License
MIT License 