import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from extensions import db
from app import create_app

app = create_app()

with app.app_context():
    db.drop_all()
    db.create_all()
    print("All tables dropped and recreated.")