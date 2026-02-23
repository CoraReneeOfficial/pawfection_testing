# details_needed_utils.py
"""
Utility functions for determining if an appointment needs additional details for review.
"""

def appointment_needs_details(dog, groomer, services_text):
    """
    Returns True if any of the required fields (dog, owner, groomer, services) are missing, or if placeholders like 'Unknown Dog' or 'Unknown Owner' are used.
    """
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
    # Services must be non-empty (strip whitespace)
    if not services_text or not services_text.strip():
        return True
    return False
