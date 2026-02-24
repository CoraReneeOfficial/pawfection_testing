#!/usr/bin/env python3
"""
Script to update the details_needed flag for appointments based on their current data.
This will help fix appointments showing "needs review" when they shouldn't be.
"""
import os
import sys
from datetime import datetime

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app import create_app
from models import db, Appointment, Dog, User
from appointments.details_needed_utils import appointment_needs_details

def update_appointment_flags(store_id=None):
    """
    Update the details_needed flag for appointments based on their current data.
    If store_id is provided, only update appointments for that store.
    """
    app = create_app()
    
    with app.app_context():
        # Query for appointments that need to be checked
        query = Appointment.query
        
        if store_id is not None:
            query = query.filter_by(store_id=store_id)
            print(f"Updating appointments for store ID: {store_id}")
        else:
            print("Updating appointments for ALL stores")
        
        appointments = query.all()
        total = len(appointments)
        print(f"Found {total} appointments to process")
        
        updated_count = 0
        
        for i, appt in enumerate(appointments, 1):
            # Get the related objects with joinedload for better performance
            dog = Dog.query.options(db.joinedload(Dog.owner)).get(appt.dog_id) if appt.dog_id else None
            groomer = User.query.get(appt.groomer_id) if appt.groomer_id else None
            
            # Determine if details are needed
            needs_details = appointment_needs_details(
                dog=dog,
                groomer=groomer,
                services_text=appt.requested_services_text or "",
                status=appt.status
            )
            
            # Only update if the flag would change
            if appt.details_needed != needs_details:
                appt.details_needed = needs_details
                updated_count += 1
                status = "needs review" if needs_details else "does NOT need review"
                print(f"  [{i}/{total}] Updated appointment {appt.id}: {status}")
            
            # Print progress every 10 appointments
            if i % 10 == 0 or i == total:
                print(f"Processed {i}/{total} appointments...")
        
        # Commit all changes at once
        if updated_count > 0:
            db.session.commit()
            print(f"\nSuccessfully updated {updated_count} appointments.")
        else:
            print("\nNo appointments needed updating.")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Update appointment details_needed flags")
    parser.add_argument("--store", type=int, help="Store ID to update (default: all stores)")
    
    args = parser.parse_args()
    
    update_appointment_flags(store_id=args.store)
