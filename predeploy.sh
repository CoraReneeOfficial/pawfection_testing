#!/bin/bash
set -e

# Ensure the virtual environment is activated and dependencies are installed
pip install -r requirements.txt

# Generate migration (if not already generated)
flask db migrate -m "Add address, phone, email, timezone to Store model" || true

# Apply migration to the database
flask db upgrade