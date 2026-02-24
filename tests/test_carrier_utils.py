import pytest
from notifications.carrier_utils import get_carrier_email, CARRIERS

def test_get_carrier_email_valid():
    """Test that valid phone numbers and carriers return the correct MMS email."""
    # Test a few known carriers
    assert get_carrier_email('9195551234', 'Verizon') == '9195551234@vzwpix.com'
    assert get_carrier_email('919-555-1234', 'AT&T') == '9195551234@mms.att.net'
    assert get_carrier_email('(919) 555-1234', 'T-Mobile') == '9195551234@tmomail.net'

    # Test the requested "SafeLink"
    assert get_carrier_email('9195551234', 'SafeLink') == '9195551234@mmst5.tracfone.com'

    # Test Tracfone directly
    assert get_carrier_email('9195551234', 'Tracfone') == '9195551234@mmst5.tracfone.com'

    # Test US Cellular preservation
    assert get_carrier_email('9195551234', 'US Cellular') == '9195551234@mms.uscc.net'

def test_get_carrier_email_invalid_phone():
    """Test that invalid phone numbers return None."""
    assert get_carrier_email('123', 'Verizon') is None
    assert get_carrier_email('919555123456', 'Verizon') is None  # Too long
    assert get_carrier_email(None, 'Verizon') is None
    assert get_carrier_email('', 'Verizon') is None

def test_get_carrier_email_unknown_carrier():
    """Test that unknown carriers return None."""
    assert get_carrier_email('9195551234', 'Unknown Carrier') is None
    assert get_carrier_email('9195551234', None) is None
    assert get_carrier_email('9195551234', '') is None

def test_all_carriers_have_values():
    """Ensure all carriers in the dictionary have a non-empty gateway string."""
    for carrier, gateway in CARRIERS.items():
        assert gateway, f"Gateway for {carrier} is empty"
        assert '@' not in gateway, f"Gateway for {carrier} should not contain '@', just the domain"

def test_phone_normalization():
    """Test that phone number normalization works correctly."""
    assert get_carrier_email('+1 (919) 555-1234', 'Verizon') == '9195551234@vzwpix.com'
    assert get_carrier_email('1-919-555-1234', 'Verizon') == '9195551234@vzwpix.com'
