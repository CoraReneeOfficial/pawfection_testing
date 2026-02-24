# details_needed_utils.py
"""
Utility functions for determining if an appointment needs additional details for review.
"""

def appointment_needs_details(dog, groomer, services_text, status=None):
    """
    Returns True if any of the required fields (dog, owner, groomer, services) are missing, or if placeholders like 'Unknown Dog' or 'Unknown Owner' are used.

    If the status is 'Completed', 'Cancelled', or 'No Show', the appointment is considered finalized and does NOT need details.
    """

    # Check status first - if completed/cancelled/no-show, no details needed regardless of missing fields
    if status and status in ['Completed', 'Cancelled', 'No Show']:
        return False

    # Dog must exist and have an owner
    if not dog or not getattr(dog, 'owner', None):
        return True
    # Dog name should not be 'Unknown Dog'
    if hasattr(dog, 'name') and dog.name and dog.name.strip().lower() == 'unknown dog':
        return True
    # Owner name should not be 'Unknown Owner'
    owner = getattr(dog, 'owner', None)
    if owner and hasattr(owner, 'name') and owner.name and owner.name.strip().lower() == 'unknown owner':
        return True
    # Groomer must exist and have a non-empty username
    if not groomer or not getattr(groomer, 'username', None) or not groomer.username.strip():
        return True
    # Services must be non-empty (strip whitespace)
    if not services_text or not services_text.strip():
        return True
    return False
