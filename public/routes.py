from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from models import Store, AppointmentRequest
from extensions import db
import json

public_bp = Blueprint('public', __name__)

@public_bp.route('/<store_username>', methods=['GET', 'POST'])
def public_store_page(store_username):
    """Public-facing store page where customers can read info and submit appointment requests."""
    store = Store.query.filter_by(username=store_username).first_or_404()

    if request.method == 'POST':
        # Gather form inputs
        customer_name = request.form.get('customer_name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        dog_name = request.form.get('dog_name', '').strip()
        preferred_date = request.form.get('preferred_date', '').strip()
        preferred_time = request.form.get('preferred_time', '').strip()
        preferred_dt = f"{preferred_date} {preferred_time}".strip() if preferred_date and preferred_time else ''
        notes = request.form.get('notes', '').strip()

        # Basic validation
        if not customer_name or not phone:
            flash('Name and phone are required.', 'danger')
            return redirect(url_for('public.public_store_page', store_username=store_username))

        new_req = AppointmentRequest(
            store_id=store.id,
            customer_name=customer_name,
            phone=phone,
            email=email,
            dog_name=dog_name,
            preferred_datetime=preferred_dt,
            notes=notes
        )
        db.session.add(new_req)
        db.session.commit()
        flash('Your request has been submitted! We will contact you soon.', 'success')
        return redirect(url_for('public.public_store_page', store_username=store_username))

    # Parse gallery images for the template
    if store.gallery_images:
        try:
            store.gallery_images_list = json.loads(store.gallery_images)
        except (json.JSONDecodeError, TypeError):
            store.gallery_images_list = []
    else:
        store.gallery_images_list = []
            
    return render_template('public_store_page.html', store=store)
