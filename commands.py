"""Commands for the Pawfection app."""
import click
from flask import Flask
from flask.cli import with_appcontext
from models import db, Store, Appointment, AppointmentRequest
from notification_system import create_notification, check_for_notifications
import random

@click.command('generate-test-notifications')
@click.option('--store-id', type=int, help='The store ID to generate notifications for')
@with_appcontext
def generate_test_notifications_command(store_id=None):
    """Generate test notifications for development and testing purposes."""
    if store_id is None:
        # Get the first store in the database if no store ID is provided
        store = Store.query.first()
        if store:
            store_id = store.id
        else:
            click.echo('No stores found in the database.')
            return
    
    # Ensure the store exists
    store = Store.query.get(store_id)
    if not store:
        click.echo(f'Store with ID {store_id} not found.')
        return
    
    click.echo(f'Generating test notifications for store {store.name} (ID: {store_id})...')
    
    # Create a test notification for pending appointment requests
    create_notification(
        store_id=store_id,
        notification_type='appointment_request',
        content=f'You have {random.randint(1, 5)} pending appointment requests.'
    )
    click.echo('Created test notification for pending appointment requests.')
    
    # Create test notifications for appointments needing review
    appointments = Appointment.query.filter_by(store_id=store_id).limit(3).all()
    for appointment in appointments:
        create_notification(
            store_id=store_id,
            notification_type='appointment_needs_review',
            content=f'Appointment for {appointment.dog.name if appointment.dog else "Unknown"} needs review.',
            reference_id=appointment.id,
            reference_type='appointment'
        )
        click.echo(f'Created test notification for appointment {appointment.id}.')
    
    # Run the check_for_notifications function to generate real notifications
    check_for_notifications(store_id)
    click.echo('Generated real notifications based on current data.')
    
    click.echo('Test notifications generated successfully.')

def register_commands(app: Flask):
    """Register CLI commands for the application."""
    app.cli.add_command(generate_test_notifications_command)
