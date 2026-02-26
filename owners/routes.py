from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app, session
from models import Owner, Dog, Appointment, ActivityLog, AppointmentRequest, Receipt
from extensions import db, csrf
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from functools import wraps
from utils import allowed_file # Keep allowed_file from utils
from utils import log_activity   # IMPORT log_activity from utils.py
from notifications.carrier_utils import CARRIERS

owners_bp = Blueprint('owners', __name__)

@owners_bp.route('/directory')
def directory():
    """
    Displays a paginated directory of owners, filtered by the current store's ID.
    Allows searching owners and their dogs within the current store.
    """
    store_id = session.get('store_id') # Get store_id from session
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Base query for owners, filtered by store_id
    owners_query = Owner.query.filter_by(store_id=store_id)

    if search_query:
        log_activity("Searched Directory", details=f"Query: '{search_query}', Store ID: {store_id}")
        search_term = f"%{search_query}%"
        # Join with Dog for filtering
        # Use selectinload to fetch ALL dogs for the matching owners in a separate query.
        # This prevents the "partial collection" issue where only matching dogs are loaded,
        # and avoids the "duplicate rows" pagination issue caused by joined loading.
        owners_query = owners_query.join(Dog, Owner.id == Dog.owner_id, isouter=True).options(selectinload(Owner.dogs)).filter(
            or_(
                Owner.name.ilike(search_term), 
                Owner.phone_number.ilike(search_term),
                Owner.email.ilike(search_term), 
                # Ensure dog search is also implicitly limited by the owner's store_id
                Dog.name.ilike(search_term)
            )
        ).distinct()
    else:
        # Use standard joinedload when not searching for efficiency (1 query)
        owners_query = owners_query.options(db.joinedload(Owner.dogs))
        log_activity("Viewed Directory page", details=f"Store ID: {store_id}")
    
    owners_pagination = owners_query.order_by(Owner.name.asc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('directory.html', owners=owners_pagination.items, pagination=owners_pagination, search_query=search_query)

@owners_bp.route('/add_owner', methods=['GET', 'POST'])
def add_owner():
    """
    Handles adding a new owner.
    Ensures phone number and email uniqueness are checked only within the current store.
    Assigns the new owner to the current store.
    """
    store_id = session.get('store_id') # Get store_id from session

    if request.method == 'POST':
        csrf.protect()
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip().lower()
        address = request.form.get('address', '').strip()
        phone_carrier = request.form.get('phone_carrier')
        text_notifications_enabled = 'text_notifications_enabled' in request.form
        email_notifications_enabled = 'email_notifications_enabled' in request.form
        
        errors = {}
        if not name: errors['name'] = "Owner Name required."
        if not phone: errors['phone'] = "Phone Number required."
        
        # Check for phone number conflict only within the current store
        if Owner.query.filter_by(phone_number=phone, store_id=store_id).first():
            errors['phone_conflict'] = f"Phone '{phone}' already exists in this store."
        
        # Check for email conflict only within the current store
        if email and Owner.query.filter_by(email=email, store_id=store_id).first():
            errors['email_conflict'] = f"Email '{email}' already exists in this store."
        
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            return render_template('add_owner.html', owner=request.form.to_dict()), 400
        
        new_owner = Owner(
            name=name, 
            phone_number=phone, 
            email=email or None, 
            address=address or None,
            phone_carrier=phone_carrier or None,
            text_notifications_enabled=text_notifications_enabled,
            email_notifications_enabled=email_notifications_enabled,
            created_by_user_id=g.user.id, 
            store_id=g.user.store_id # Assign current user's store_id to the new owner
        )
        try:
            db.session.add(new_owner)
            db.session.commit()
            log_activity("Added Owner", details=f"Name: {name}, Phone: {phone}, Store ID: {store_id}")
            flash(f"Owner '{name}' added!", "success")
            return redirect(url_for('owners.directory'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding owner: {e}", exc_info=True)
            flash("Error adding owner.", "danger")
            return render_template('add_owner.html', owner=request.form.to_dict()), 500
    
    log_activity("Viewed Add Owner page", details=f"Store ID: {store_id}")
    return render_template('add_owner.html', owner={}, carriers=CARRIERS)

@owners_bp.route('/owner/<int:owner_id>')
def view_owner(owner_id):
    """
    Displays the profile of a specific owner.
    Ensures the owner belongs to the current store.
    """
    store_id = session.get('store_id') # Get store_id from session

    # Fetch owner, ensuring they belong to the current store
    owner = Owner.query.options(
        db.joinedload(Owner.dogs) 
    ).filter_by(id=owner_id, store_id=store_id).first_or_404()

    log_activity("Viewed Owner Profile", details=f"Owner: {owner.name} (ID: {owner_id}), Store ID: {store_id}")
    return render_template('owner_profile.html', owner=owner)

@owners_bp.route('/owner/<int:owner_id>/edit', methods=['GET', 'POST'])
def edit_owner(owner_id):
    """
    Handles editing the profile of a specific owner.
    Ensures the owner belongs to the current store.
    Ensures phone number and email uniqueness are checked only within the current store.
    """
    store_id = session.get('store_id') # Get store_id from session

    # Fetch owner to edit, ensuring they belong to the current store
    owner_to_edit = Owner.query.filter_by(id=owner_id, store_id=store_id).first_or_404()

    if request.method == 'POST':
        csrf.protect()
        original_phone = owner_to_edit.phone_number
        original_email = owner_to_edit.email
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip().lower()
        address = request.form.get('address', '').strip()
        phone_carrier = request.form.get('phone_carrier')
        text_notifications_enabled = 'text_notifications_enabled' in request.form
        email_notifications_enabled = 'email_notifications_enabled' in request.form
        
        errors = {}
        if not name: errors['name'] = "Owner Name required."
        if not phone: errors['phone'] = "Phone Number required."
        
        # Check for phone number conflict only within the current store, excluding the current owner
        if phone != original_phone and Owner.query.filter(Owner.id != owner_id, Owner.phone_number == phone, Owner.store_id==store_id).first():
            errors['phone_conflict'] = f"Phone '{phone}' already exists in this store."
        
        # Check for email conflict only within the current store, excluding the current owner
        if email and email != original_email and Owner.query.filter(Owner.id != owner_id, Owner.email == email, Owner.store_id==store_id).first():
            errors['email_conflict'] = f"Email '{email}' already exists in this store."
        
        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = {'id': owner_id, 'name': name, 'phone_number': phone, 'email': email, 'address': address}
            return render_template('edit_owner.html', owner=form_data), 400
        
        owner_to_edit.name = name
        owner_to_edit.phone_number = phone
        owner_to_edit.email = email or None
        owner_to_edit.address = address or None
        owner_to_edit.phone_carrier = phone_carrier or None
        owner_to_edit.text_notifications_enabled = text_notifications_enabled
        owner_to_edit.email_notifications_enabled = email_notifications_enabled
        
        try:
            db.session.commit()
            log_activity("Edited Owner", details=f"Owner ID: {owner_id}, Name: {name}, Store ID: {store_id}")
            flash(f"Owner '{name}' updated!", "success")
            return redirect(url_for('owners.view_owner', owner_id=owner_id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing owner {owner_id}: {e}", exc_info=True)
            flash("Error updating owner.", "danger")
            return render_template('edit_owner.html', owner=owner_to_edit), 500
    
    log_activity("Viewed Edit Owner page", details=f"Owner ID: {owner_id}, Store ID: {store_id}")
    return render_template('edit_owner.html', owner=owner_to_edit, carriers=CARRIERS)

@owners_bp.route('/owner/<int:owner_id>/delete', methods=['POST'])
def delete_owner(owner_id):
    """
    Securely deletes an owner and all their dogs and appointments, only if the owner belongs to the current store.
    Handles cleanup of associated records that don't cascade automatically.
    """
    csrf.protect()
    store_id = session.get('store_id')
    owner = Owner.query.filter_by(id=owner_id, store_id=store_id).first()
    if not owner:
        flash('Owner not found or does not belong to this store.', 'danger')
        return redirect(url_for('owners.directory'))
    try:
        owner_name = owner.name

        # 1. Unlink AppointmentRequests associated with this owner
        requests = AppointmentRequest.query.filter_by(owner_id=owner.id).all()
        for req in requests:
            req.owner_id = None

        # 2. Delete Receipts associated with appointments of this owner's dogs
        # Since Receipt.appointment_id is nullable=False, we must delete them before deleting appointments
        # Appointments will be deleted by cascade when Dog is deleted, which is deleted when Owner is deleted

        # Get all dog IDs for this owner
        dog_ids = [d.id for d in owner.dogs]

        if dog_ids:
            # Get all appointment IDs for these dogs
            appointment_ids = [a.id for a in Appointment.query.filter(Appointment.dog_id.in_(dog_ids)).all()]

            if appointment_ids:
                # Delete receipts for these appointments
                Receipt.query.filter(Receipt.appointment_id.in_(appointment_ids)).delete(synchronize_session=False)

        db.session.delete(owner)
        db.session.commit()
        log_activity("Deleted Owner", details=f"Owner: {owner_name} (ID: {owner_id}), Store ID: {store_id}")
        flash(f'Owner "{owner_name}" and all their dogs/appointments have been deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting owner {owner_id}: {e}", exc_info=True)
        flash('Error deleting owner.', 'danger')
    return redirect(url_for('owners.directory'))
