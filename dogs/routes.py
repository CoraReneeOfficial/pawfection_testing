from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app, session
from models import Dog, Owner, Appointment, ActivityLog, Store
from extensions import db
from werkzeug.utils import secure_filename
import os
import uuid
from functools import wraps
from utils import allowed_file # Keep allowed_file from utils
from utils import log_activity   # IMPORT log_activity from utils.py
from utils import subscription_required  # Import subscription_required decorator
import pytz
from dateutil import tz

dogs_bp = Blueprint('dogs', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def _handle_dog_picture_upload(dog_instance, request_files):
    """
    Handles the upload of a dog's picture.
    Deletes the old picture if a new one is uploaded.
    """
    if 'dog_picture' not in request_files:
        return None
    file = request_files['dog_picture']
    import imghdr
    if file and file.filename != '' and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        # Generate a unique filename using UUID to prevent collisions
        new_filename = secure_filename(f"dog_{dog_instance.id or 'temp'}_{uuid.uuid4().hex[:8]}.{ext}")
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], new_filename)
        os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True) # Ensure upload directory exists

        # Check MIME type using imghdr BEFORE saving
        file.stream.seek(0)
        header_bytes = file.read(512)
        file.stream.seek(0)
        detected_type = imghdr.what(None, h=header_bytes)
        if detected_type not in {'jpeg', 'png', 'gif', 'webp'}:
            flash("Uploaded file is not a valid image type.", "danger")
            current_app.logger.warning(f"Rejected dog picture upload: invalid MIME type {detected_type}")
            return None

        # If there's an old picture, delete it
        if dog_instance.picture_filename and dog_instance.picture_filename != new_filename:
            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], dog_instance.picture_filename)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    current_app.logger.info(f"Deleted old dog pic: {old_path}")
                except OSError as e_rem:
                    current_app.logger.error(f"Error deleting old dog pic {old_path}: {e_rem}")
        try:
            file.save(file_path)
            current_app.logger.info(f"Saved new dog pic: {file_path}")
            return new_filename
        except Exception as e_save:
            flash(f"Failed to save picture: {e_save}", "warning")
            current_app.logger.error(f"Failed to save dog pic {file_path}: {e_save}", exc_info=True)
    elif file and file.filename != '':
        flash("Invalid file type for dog picture.", "warning")
        current_app.logger.warning(f"Rejected dog picture upload: disallowed extension for file {file.filename}")
    return None

@dogs_bp.route('/owner/<int:owner_id>/add_dog', methods=['GET', 'POST'])
@subscription_required
def add_dog(owner_id):
    """
    Handles adding a new dog for a specific owner.
    Ensures the owner belongs to the current store.
    """
    store_id = session.get('store_id') # Get store_id from session

    # Fetch owner, ensuring they belong to the current store
    owner = Owner.query.filter_by(id=owner_id, store_id=store_id).first_or_404()

    if request.method == 'POST':
        dog_name = request.form.get('dog_name', '').strip()
        if not dog_name:
            flash("Dog Name required.", "danger")
            return render_template('add_dog.html', owner=owner, dog=request.form.to_dict()), 400
        
        new_dog = Dog(
            name=dog_name,
            breed=(request.form.get('breed', '').strip() or None),
            birthday=(request.form.get('birthday', '').strip() or None),
            temperament=(request.form.get('temperament', '').strip() or None),
            hair_style_notes=(request.form.get('hair_style_notes', '').strip() or None),
            aggression_issues=(request.form.get('aggression_issues', '').strip() or None),
            anxiety_issues=(request.form.get('anxiety_issues', '').strip() or None),
            other_notes=(request.form.get('other_notes', '').strip() or None),
            owner_id=owner.id,
            created_by_user_id=g.user.id,
            store_id=owner.store_id # Dog inherits store_id from its owner
        )
        try:
            db.session.add(new_dog)
            db.session.flush() # Flush to get new_dog.id for picture upload filename
            
            uploaded_filename = _handle_dog_picture_upload(new_dog, request.files)
            if uploaded_filename:
                new_dog.picture_filename = uploaded_filename
            
            db.session.commit()
            log_activity("Added Dog", details=f"Name: {dog_name}, Owner: {owner.name}")
            flash(f"Dog '{dog_name}' added for {owner.name}!", "success")
            return redirect(url_for('owners.view_owner', owner_id=owner.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding dog: {e}", exc_info=True)
            flash("Error adding dog.", "danger")
            return render_template('add_dog.html', owner=owner, dog=request.form.to_dict()), 500
    
    log_activity("Viewed Add Dog page", details=f"For Owner: {owner.name}")
    return render_template('add_dog.html', owner=owner, dog={})

@dogs_bp.route('/dog/<int:dog_id>')
@subscription_required
def view_dog(dog_id):
    """
    Displays the profile of a specific dog.
    Ensures the dog belongs to the current store.
    """
    store_id = session.get('store_id') # Get store_id from session

    # Fetch dog, ensuring it belongs to the current store
    dog = Dog.query.options(
        db.joinedload(Dog.owner) 
    ).filter_by(id=dog_id, store_id=store_id).first_or_404()

    # Appointments for this dog will inherently be filtered by dog.id,
    # and since dog.store_id is checked, these appointments will also belong to the current store.
    appointments_for_dog = dog.appointments.options(db.joinedload(Appointment.groomer)).all()

    # Fetch store and its timezone
    store = db.session.get(Store, store_id)
    store_tz_str = getattr(store, 'timezone', None) or 'UTC'
    try:
        BUSINESS_TIMEZONE = pytz.timezone(store_tz_str)
    except Exception:
        BUSINESS_TIMEZONE = pytz.UTC
    log_activity("Viewed Dog Profile", details=f"Dog: {dog.name}")
    return render_template('dog_profile.html', dog=dog, appointments=appointments_for_dog, BUSINESS_TIMEZONE=BUSINESS_TIMEZONE, tz=tz)

@dogs_bp.route('/dog/<int:dog_id>/edit', methods=['GET', 'POST'])
@subscription_required
def edit_dog(dog_id):
    """
    Handles editing the profile of a specific dog.
    Ensures the dog belongs to the current store.
    """
    store_id = session.get('store_id') # Get store_id from session

    # Fetch dog, ensuring it belongs to the current store
    dog = Dog.query.options(db.joinedload(Dog.owner)).filter_by(id=dog_id, store_id=store_id).first_or_404()

    if request.method == 'POST':
        dog_name = request.form.get('dog_name', '').strip()
        if not dog_name:
            flash("Dog Name required.", "danger")
            return render_template('edit_dog.html', dog=dog), 400
        
        dog.name = dog_name
        dog.breed = request.form.get('breed', '').strip() or None
        dog.birthday = request.form.get('birthday', '').strip() or None
        dog.temperament = request.form.get('temperament', '').strip() or None
        dog.hair_style_notes = request.form.get('hair_style_notes', '').strip() or None
        dog.aggression_issues = request.form.get('aggression_issues', '').strip() or None
        dog.anxiety_issues = request.form.get('anxiety_issues', '').strip() or None
        dog.other_notes = request.form.get('other_notes', '').strip() or None
        dog.vaccines = request.form.get('vaccines', '').strip() or None
        
        try:
            uploaded_filename = _handle_dog_picture_upload(dog, request.files)
            if uploaded_filename:
                dog.picture_filename = uploaded_filename
            
            db.session.commit()
            log_activity("Edited Dog Profile", details=f"Dog: {dog_name}")
            flash(f"Profile for '{dog_name}' updated!", "success")
            return redirect(url_for('dogs.view_dog', dog_id=dog.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating dog {dog_id}: {e}", exc_info=True)
            flash("Error updating dog profile.", "danger")
            # Preserve current form data on error
            current_data = dog
            current_data.name = dog_name # Update name in current_data to reflect user's input
            return render_template('edit_dog.html', dog=current_data), 500
    
    log_activity("Viewed Edit Dog page", details=f"Dog: {dog.name}")
    return render_template('edit_dog.html', dog=dog)

@dogs_bp.route('/dog/<int:dog_id>/delete', methods=['POST'])
@subscription_required
def delete_dog(dog_id):
    """
    Handles deleting a specific dog.
    Ensures the dog belongs to the current store.
    """
    store_id = session.get('store_id') # Get store_id from session

    # Fetch dog to delete, ensuring it belongs to the current store
    dog_to_delete = Dog.query.filter_by(id=dog_id, store_id=store_id).first_or_404()
    
    dog_name = dog_to_delete.name
    owner_id = dog_to_delete.owner_id # Keep owner_id for redirection
    pic_to_delete = dog_to_delete.picture_filename
    
    try:
        db.session.delete(dog_to_delete)
        db.session.commit()
        
        # Delete associated picture file if it exists
        if pic_to_delete:
            path = os.path.join(current_app.config['UPLOAD_FOLDER'], pic_to_delete)
            if os.path.exists(path):
                try:
                    os.remove(path)
                    current_app.logger.info(f"Deleted dog pic: {path}")
                except OSError as e_rem:
                    current_app.logger.error(f"Error deleting dog pic file {path}: {e_rem}")
        
        log_activity("Deleted Dog", details=f"Dog: {dog_name}")
        flash(f"Dog '{dog_name}' deleted.", "success")
        return redirect(url_for('owners.view_owner', owner_id=owner_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting dog '{dog_name}': {e}", exc_info=True)
        flash(f"Error deleting '{dog_name}'.", "danger")
        return redirect(url_for('dogs.view_dog', dog_id=dog_id))

@dogs_bp.route('/dog/<int:dog_id>/service-history')
@subscription_required
def dog_service_history(dog_id):
    """
    Display the complete service history for a specific dog with search and filtering options.
    """
    store_id = session.get('store_id')
    
    # Fetch dog, ensuring it belongs to the current store
    dog = Dog.query.options(
        db.joinedload(Dog.owner) 
    ).filter_by(id=dog_id, store_id=store_id).first_or_404()
    
    # Get query parameters for filtering
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    status = request.args.get('status')
    service = request.args.get('service')
    search_query = request.args.get('search')
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Number of appointments per page
    
    # Base query for dog's appointments
    query = dog.appointments.options(db.joinedload(Appointment.groomer))
    
    # Apply filters if provided
    is_filtered = False
    if date_from:
        is_filtered = True
        query = query.filter(Appointment.appointment_datetime >= date_from)
    
    if date_to:
        is_filtered = True
        query = query.filter(Appointment.appointment_datetime <= date_to + ' 23:59:59')
    
    if status:
        is_filtered = True
        query = query.filter(Appointment.status == status)
    
    if service:
        is_filtered = True
        query = query.filter(Appointment.requested_services_text.ilike(f'%{service}%'))
    
    if search_query:
        is_filtered = True
        query = query.filter(Appointment.notes.ilike(f'%{search_query}%'))
    
    # Paginate the results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    appointments = pagination.items
    
    # Fetch store and its timezone
    store = db.session.get(Store, store_id)
    store_tz_str = getattr(store, 'timezone', None) or 'UTC'
    try:
        BUSINESS_TIMEZONE = pytz.timezone(store_tz_str)
    except Exception:
        BUSINESS_TIMEZONE = pytz.UTC
    
    log_activity("Viewed Dog Service History", details=f"Dog: {dog.name}, Filtered: {is_filtered}")
    
    return render_template(
        'dog_service_history.html',
        dog=dog,
        appointments=appointments,
        pagination=pagination,
        BUSINESS_TIMEZONE=BUSINESS_TIMEZONE,
        is_filtered=is_filtered,
        request=request,
        tz=tz
    )
