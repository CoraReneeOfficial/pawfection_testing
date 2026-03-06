with open('appointments/routes.py', 'r') as f:
    content = f.read()

target = """            event = service.events().get(calendarId=store.user.google_calendar_id, eventId=appt.google_event_id).execute()
            event['description'] = f"Status: {new_status}\\n" + event.get('description', '')
            service.events().update(calendarId=store.user.google_calendar_id, eventId=appt.google_event_id, body=event).execute()"""

replacement = """            event = service.events().get(calendarId=store.user.google_calendar_id, eventId=appt.google_event_id).execute()
            desc = event.get('description', '')
            if 'Status: ' in desc:
                desc = re.sub(r'Status: .+\\n', f'Status: {new_status}\\n', desc, count=1)
            else:
                desc = f"Status: {new_status}\\n" + desc
            event['description'] = desc
            service.events().update(calendarId=store.user.google_calendar_id, eventId=appt.google_event_id, body=event).execute()"""

if target in content:
    content = content.replace(target, replacement)
    with open('appointments/routes.py', 'w') as f:
        f.write(content)
    print("appointments/routes.py calendar sync patched")
