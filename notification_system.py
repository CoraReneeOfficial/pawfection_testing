from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, jsonify
)
from models import Notification, Appointment, AppointmentRequest, ActivityLog, db
from werkzeug.exceptions import abort
from flask_login import login_required

bp = Blueprint('notification_system', __name__, url_prefix='/notifications')

@bp.route('/')
@login_required
def view_all():
    """View all notifications for the current user."""
    # Get all notifications for this user's store
    notifications = Notification.query.filter_by(
        store_id=g.user.store_id,
        is_read=False
    ).order_by(Notification.created_at.desc()).all()
    
    # Mark all as read when viewing the full notification page
    for notification in notifications:
        notification.is_read = True
    
    db.session.commit()
    
    return render_template('notifications/all.html', notifications=notifications)

@bp.route('/mark_read/<int:id>', methods=['POST', 'GET'])
@login_required
def mark_read(id):
    """Mark a notification as read."""
    notification = Notification.query.get_or_404(id)
    
    # Make sure the notification belongs to the user's store
    if notification.store_id != g.user.store_id:
        abort(403)
    
    notification.is_read = True
    db.session.commit()
    
    # Redirect back to referring page
    return redirect(request.referrer or url_for('notification_system.view_all'))

@bp.route('/mark_all_read', methods=['POST', 'GET'])
@login_required
def mark_all_read():
    """Mark all notifications as read for the current user's store."""
    # Get all unread notifications for this user's store
    notifications = Notification.query.filter_by(
        store_id=g.user.store_id,
        is_read=False
    ).all()
    
    # Mark all as read
    for notification in notifications:
        notification.is_read = True
    
    db.session.commit()
    flash('All notifications marked as read.', 'success')
    
    # Redirect back to referring page
    return redirect(request.referrer or url_for('notification_system.view_all'))
    
    # If it's an AJAX request, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})
    
    # Otherwise redirect back to where they came from
    return redirect(request.referrer or url_for('notification_system.view_all'))

# Function to generate a link for a notification based on its type and reference
def get_notification_link(notification):
    """Generate the appropriate link for a notification based on its type."""
    if notification.type == 'appointment_request':
        return url_for('management.pending_appointments')
    elif notification.type == 'appointment_needs_review':
        if notification.reference_id:
            # Direct to appointment edit page if we have a reference_id
            return url_for('appointments.edit_appointment', appointment_id=notification.reference_id)
        else:
            # Otherwise go to the needs_review page which lists all appointments needing review
            return url_for('appointments.needs_review')
    else:
        # Default to notifications page
        return url_for('notification_system.view_all')

# Helper function to create a notification
def create_notification(store_id, notification_type, content, reference_id=None, reference_type=None, user_id=None):
    """Create a new notification in the database."""
    notification = Notification(
        store_id=store_id,
        user_id=user_id,
        type=notification_type,
        content=content,
        reference_id=reference_id,
        reference_type=reference_type,
        is_read=False
    )
    
    db.session.add(notification)
    db.session.commit()
    
    return notification

# Check for items that need attention and create notifications
def check_for_notifications(store_id):
    """Check for items that need attention and create notifications if needed."""
    # Check for pending appointment requests
    pending_requests = AppointmentRequest.query.filter_by(
        store_id=store_id,
        status='pending'
    ).count()
    
    if pending_requests > 0:
        # Check if we already have a notification for this
        existing = Notification.query.filter_by(
            store_id=store_id,
            type='appointment_request',
            is_read=False
        ).first()
        
        if not existing:
            create_notification(
                store_id=store_id,
                notification_type='appointment_request',
                content=f'You have {pending_requests} pending appointment request{"s" if pending_requests > 1 else ""}.'
            )
    
    # Check for appointments that need review (have details_needed flag)
    appointments_needing_review = Appointment.query.filter_by(
        store_id=store_id,
        details_needed=True
    ).all()
    
    for appointment in appointments_needing_review:
        # Check if we already have a notification for this appointment
        existing = Notification.query.filter_by(
            store_id=store_id,
            type='appointment_needs_review',
            reference_id=appointment.id,
            is_read=False
        ).first()
        
        if not existing:
            create_notification(
                store_id=store_id,
                notification_type='appointment_needs_review',
                content=f'Appointment for {appointment.dog.name} needs review.',
                reference_id=appointment.id,
                reference_type='appointment'
            )
