import re

CARRIERS = {
    'Alltel': 'mms.alltelwireless.com',
    'AT&T': 'mms.att.net',
    'Boost Mobile': 'myboostmobile.com',
    'C-Spire': 'cspire1.com',
    'Consumer Cellular': 'mailmymobile.net',
    'Cricket': 'mms.cricketwireless.net',
    'Google Fi': 'msg.fi.google.com',
    'MetroPCS': 'mymetropcs.com',
    'Mint Mobile': 'mailmymobile.net',
    'Page Plus': 'vzwpix.com',
    'Republic Wireless': 'text.republicwireless.com',
    'SafeLink': 'mmst5.tracfone.com',
    'Simple Mobile': 'smtext.com',
    'Spectrum Mobile': 'vzwpix.com',
    'Sprint': 'pm.sprint.com',
    'Straight Talk': 'mypixmessages.com',
    'T-Mobile': 'tmomail.net',
    'Ting': 'message.ting.com',
    'Tracfone': 'mmst5.tracfone.com',
    'US Cellular': 'mms.uscc.net',
    'Verizon': 'vzwpix.com',
    'Virgin Mobile': 'vmpix.com',
    'Xfinity Mobile': 'mypixmessages.com',
}

def get_carrier_email(phone, carrier_name):
    """
    Returns the email address for sending SMS to the given phone number via the carrier's gateway.
    Returns None if carrier is not found or phone number is invalid.
    """
    if not phone or not carrier_name:
        return None

    gateway = CARRIERS.get(carrier_name)
    if not gateway:
        return None

    # Remove all non-digit characters from phone number
    clean_phone = re.sub(r'\D', '', phone)

    # Ensure phone number is 10 digits (remove leading 1 if present)
    if len(clean_phone) == 11 and clean_phone.startswith('1'):
        clean_phone = clean_phone[1:]

    if len(clean_phone) != 10:
        return None

    return f"{clean_phone}@{gateway}"
