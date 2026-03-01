import re

with open("app.py", "r") as f:
    text = f.read()

# I'll add the import right before using joinedload if it's not at the top level
text = text.replace("from models import ActivityLog", "from models import ActivityLog\n        from sqlalchemy.orm import joinedload")

with open("app.py", "w") as f:
    f.write(text)
