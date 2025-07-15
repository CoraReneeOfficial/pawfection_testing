from flask import Blueprint, flash, redirect, render_template, request, url_for
from models import Store, AppointmentRequest
from notification_system import check_for_notifications
from extensions import db

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
        
        # Generate notification for the new appointment request
        check_for_notifications(store.id)
        
        flash('Your request has been submitted! We will contact you soon.', 'success')
        return redirect(url_for('public.public_store_page', store_username=store_username))

    return render_template('public_store_page.html', store=store)
