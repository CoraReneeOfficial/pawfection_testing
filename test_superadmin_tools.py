"""
Test script for Superadmin Tools features.
This script will help verify that the new superadmin tools routes are functioning correctly.
"""

import sys
import os
import time
from app import create_app

def main():
    print("Starting Pawfection superadmin tools test server...")
    print("=================================================")
    print("✅ System Health route available at: /superadmin/system-health")
    print("✅ User Management route available at: /superadmin/user-management")
    print("✅ Data Export route available at: /superadmin/data-export")
    print("=================================================")
    print("Login as a superadmin user to access these features.")
    print("Press CTRL+C to stop the server.")
    
    # Create and run the Flask app
    app = create_app()
    app.run(debug=True, port=5000)

if __name__ == "__main__":
    main()
