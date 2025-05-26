from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app
from models import Dog, Owner, Appointment, ActivityLog
from extensions import db
from werkzeug.utils import secure_filename
import os
import uuid
from functools import wraps
from utils import allowed_file, log_activity

dogs_bp = Blueprint('dogs', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def _handle_dog_picture_upload(dog_instance, request_files):
    if 'dog_picture' not in request_files: return None
    file = request_files['dog_picture']
    if file and file.filename != '' and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        new_filename = secure_filename(f"dog_{dog_instance.id or 'temp'}_{uuid.uuid4().hex[:8]}.{ext}")
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], new_filename)
        os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
        if dog_instance.picture_filename and dog_instance.picture_filename != new_filename:
            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], dog_instance.picture_filename)
            if os.path.exists(old_path):
                try: os.remove(old_path); current_app.logger.info(f"Deleted old dog pic: {old_path}")
                except OSError as e_rem: current_app.logger.error(f"Error deleting old dog pic {old_path}: {e_rem}")
        try:
            file.save(file_path); current_app.logger.info(f"Saved new dog pic: {file_path}"); return new_filename
        except Exception as e_save:
            flash(f"Failed to save picture: {e_save}", "warning")
            current_app.logger.error(f"Failed to save dog pic {file_path}: {e_save}", exc_info=True)
    elif file and file.filename != '': flash("Invalid file type for dog picture.", "warning")
    return None

@dogs_bp.route('/owner/<int:owner_id>/add_dog', methods=['GET', 'POST'])
def add_dog(owner_id):
    owner = Owner.query.get_or_404(owner_id)
    if request.method == 'POST':
        dog_name = request.form.get('dog_name', '').strip()
        if not dog_name: flash("Dog Name required.", "danger"); return render_template('add_dog.html', owner=owner, dog=request.form.to_dict()), 400
        new_dog = Dog(
            name=dog_name, breed=(request.form.get('breed', '').strip() or None),
            birthday=(request.form.get('birthday', '').strip() or None),
            temperament=(request.form.get('temperament', '').strip() or None),
            hair_style_notes=(request.form.get('hair_style_notes', '').strip() or None),
            aggression_issues=(request.form.get('aggression_issues', '').strip() or None),
            anxiety_issues=(request.form.get('anxiety_issues', '').strip() or None),
            other_notes=(request.form.get('other_notes', '').strip() or None),
            owner_id=owner.id, created_by_user_id=g.user.id
        )
        try:
            db.session.add(new_dog); db.session.flush()
            uploaded_filename = _handle_dog_picture_upload(new_dog, request.files)
            if uploaded_filename: new_dog.picture_filename = uploaded_filename
            db.session.commit()
            log_activity("Added Dog", details=f"Name: {dog_name}, Owner: {owner.name}")
            flash(f"Dog '{dog_name}' added for {owner.name}!", "success"); return redirect(url_for('owners.view_owner', owner_id=owner.id))
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"Error adding dog: {e}", exc_info=True)
            flash("Error adding dog.", "danger"); return render_template('add_dog.html', owner=owner, dog=request.form.to_dict()), 500
    log_activity("Viewed Add Dog page", details=f"For Owner: {owner.name}")
    return render_template('add_dog.html', owner=owner, dog={})

@dogs_bp.route('/dog/<int:dog_id>')
def view_dog(dog_id):
    dog = Dog.query.options(
        db.joinedload(Dog.owner) 
    ).get_or_404(dog_id)
    appointments_for_dog = dog.appointments.options(db.joinedload(Appointment.groomer)).all()
    log_activity("Viewed Dog Profile", details=f"Dog: {dog.name}")
    return render_template('dog_profile.html', dog=dog, appointments=appointments_for_dog)

@dogs_bp.route('/dog/<int:dog_id>/edit', methods=['GET', 'POST'])
def edit_dog(dog_id):
    dog = Dog.query.options(db.joinedload(Dog.owner)).get_or_404(dog_id)
    if request.method == 'POST':
        dog_name = request.form.get('dog_name', '').strip()
        if not dog_name: flash("Dog Name required.", "danger"); return render_template('edit_dog.html', dog=dog), 400
        dog.name = dog_name
        dog.breed = request.form.get('breed', '').strip() or None
        dog.birthday = request.form.get('birthday', '').strip() or None
        dog.temperament = request.form.get('temperament', '').strip() or None
        dog.hair_style_notes = request.form.get('hair_style_notes', '').strip() or None
        dog.aggression_issues = request.form.get('aggression_issues', '').strip() or None
        dog.anxiety_issues = request.form.get('anxiety_issues', '').strip() or None
        dog.other_notes = request.form.get('other_notes', '').strip() or None
        try:
            uploaded_filename = _handle_dog_picture_upload(dog, request.files)
            if uploaded_filename: dog.picture_filename = uploaded_filename
            db.session.commit()
            log_activity("Edited Dog Profile", details=f"Dog: {dog_name}")
            flash(f"Profile for '{dog_name}' updated!", "success"); return redirect(url_for('dogs.view_dog', dog_id=dog.id))
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"Error updating dog {dog_id}: {e}", exc_info=True)
            flash("Error updating dog profile.", "danger")
            current_data = dog; current_data.name = dog_name
            return render_template('edit_dog.html', dog=current_data), 500
    log_activity("Viewed Edit Dog page", details=f"Dog: {dog.name}")
    return render_template('edit_dog.html', dog=dog)

@dogs_bp.route('/dog/<int:dog_id>/delete', methods=['POST'])
def delete_dog(dog_id):
    dog_to_delete = Dog.query.get_or_404(dog_id)
    dog_name = dog_to_delete.name; owner_id = dog_to_delete.owner_id
    pic_to_delete = dog_to_delete.picture_filename
    try:
        db.session.delete(dog_to_delete); db.session.commit()
        if pic_to_delete:
            path = os.path.join(current_app.config['UPLOAD_FOLDER'], pic_to_delete)
            if os.path.exists(path):
                try: os.remove(path); current_app.logger.info(f"Deleted dog pic: {path}")
                except OSError as e_rem: current_app.logger.error(f"Error deleting dog pic file {path}: {e_rem}")
        log_activity("Deleted Dog", details=f"Dog: {dog_name}")
        flash(f"Dog '{dog_name}' deleted.", "success"); return redirect(url_for('owners.view_owner', owner_id=owner_id))
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Error deleting dog '{dog_name}': {e}", exc_info=True)
        flash(f"Error deleting '{dog_name}'.", "danger"); return redirect(url_for('dogs.view_dog', dog_id=dog_id)) 