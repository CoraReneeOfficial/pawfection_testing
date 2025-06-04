#!/bin/bash
set -e

# Ensure the virtual environment is activated and dependencies are installed
pip install -r requirements.txt

# Run automatic migration script
python auto_migrate.py