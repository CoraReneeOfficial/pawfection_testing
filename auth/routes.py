from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, current_app
from models import User, ActivityLog
from extensions import db
from functools import wraps
import datetime
from datetime import timezone
from sqlalchemy.exc import IntegrityError
from utils import allowed_file, log_activity

auth_bp = Blueprint('auth', __name__)

def check_initial_setup():
    return User.query.first() is None

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if check_initial_setup():
        flash("Please complete initial setup.", "warning")
        return redirect(url_for('auth.initial_setup'))
    if getattr(g, 'user', None):
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash("Username and password required.", "danger")
            return render_template('login.html'), 400
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            g.user = user
            log_activity("Logged in")
            flash(f"Welcome back, {user.username}!", "success")
            next_page = request.args.get('next')
            if next_page and not (next_page.startswith('/') or next_page.startswith(request.host_url)):
                current_app.logger.warning(f"Invalid 'next' URL: {next_page}")
                next_page = None
            return redirect(next_page or url_for('dashboard'))
        else:
            flash("Invalid username or password.", "danger")
            return render_template('login.html'), 401
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    log_activity("Logged out")
    session.pop('user_id', None)
    g.user = None
    flash("Logged out successfully.", "info")
    return redirect(url_for('auth.login'))

@auth_bp.route('/initial_setup', methods=['GET', 'POST'])
def initial_setup():
    if not check_initial_setup():
        flash("Initial setup already completed.", "info")
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        errors = False
        if not username:
            flash("Username required.", "danger")
            errors = True
        if not password:
            flash("Password required.", "danger")
            errors = True
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            errors = True
        if len(password) < 8 and password:
            flash("Password too short (min 8 chars).", "danger")
            errors = True
        if errors:
            return render_template('initial_setup.html'), 400
        admin_user = User(username=username, is_admin=True, is_groomer=True)
        admin_user.set_password(password)
        try:
            db.session.add(admin_user)
            db.session.commit()
            created_user = User.query.filter_by(username=username).first()
            if created_user:
                setup_log = ActivityLog(user_id=created_user.id, action="Initial admin account created", details=f"Username: {username}")
                db.session.add(setup_log)
                db.session.commit()
            flash("Admin account created! Please log in.", "success")
            return redirect(url_for('auth.login'))
        except IntegrityError:
            db.session.rollback()
            flash("Username taken (IntegrityError).", "danger")
            current_app.logger.error("IntegrityError during initial_setup.")
            return render_template('initial_setup.html'), 500
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error initial setup: {e}", exc_info=True)
            flash("Error during setup.", "danger")
            return render_template('initial_setup.html'), 500
    return render_template('initial_setup.html') 