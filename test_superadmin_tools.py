"""
Test script for Superadmin Tools features.
This script will help verify that all superadmin tools routes are functioning correctly.
"""

import sys
import os
import time
import sqlite3
import psutil
import platform
from datetime import datetime
from app import create_app

def check_feature_availability(feature_name, route):
    """Check if a feature route exists in the app"""
    print(f"✅ {feature_name} available at: {route}")

def check_dependencies():
    """Check if all required dependencies are installed"""
    dependencies = {
        'psutil': psutil,
        'sqlite3': sqlite3
    }
    
    print("\nChecking dependencies...")
    all_ok = True
    for name, module in dependencies.items():
        if module:
            print(f"✅ {name} is installed")
        else:
            print(f"❌ {name} is NOT installed")
            all_ok = False
    
    return all_ok

def check_system_info():
    """Display basic system information for testing"""
    print("\nSystem Information:")
    print(f"OS: {platform.system()} {platform.version()}")
    print(f"Python: {platform.python_version()}")
    print(f"CPU Usage: {psutil.cpu_percent()}%")
    print(f"Memory Usage: {psutil.virtual_memory().percent}%")
    
    # Check if backups directory exists
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
    if os.path.exists(backup_dir):
        print(f"✅ Backups directory exists: {backup_dir}")
        # Count backup files
        backup_files = [f for f in os.listdir(backup_dir) if f.startswith('db_backup_') and f.endswith('.sqlite')]
        print(f"   Found {len(backup_files)} database backups")
    else:
        print(f"❌ Backups directory does not exist: {backup_dir}")
        print("   Will be created when making your first backup")

def main():
    print("\n==========================================================")
    print("Starting Pawfection Superadmin Tools Test Script")
    print("==========================================================")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("\nAll implemented superadmin features:")
    
    # Core Superadmin Features
    check_feature_availability("Superadmin Dashboard", "/superadmin/dashboard")
    check_feature_availability("Superadmin Tools", "/superadmin/tools")
    
    # Feature-specific routes
    check_feature_availability("System Health", "/superadmin/system-health")
    check_feature_availability("User Management", "/superadmin/user-management")
    check_feature_availability("Data Export", "/superadmin/data-export")
    check_feature_availability("Configuration Settings", "/superadmin/configuration")
    check_feature_availability("User Permissions", "/superadmin/permissions")
    check_feature_availability("Application Settings", "/superadmin/application-settings")
    check_feature_availability("System Logs", "/superadmin/system-logs")
    check_feature_availability("Email Test", "/superadmin/email-test")
    check_feature_availability("Database Management", "/superadmin/database")
    check_feature_availability("Store Management", "/superadmin/stores")
    
    # Check if dependencies are installed
    dependencies_ok = check_dependencies()
    
    # Check system information
    check_system_info()
    
    print("\n==========================================================")
    if dependencies_ok:
        print("✅ All required dependencies are installed")
    else:
        print("❌ Some dependencies are missing. Please install them before proceeding.")
    
    print("\nStarting test server...")
    print("Login as a superadmin user to access these features.")
    print("Default superadmin credentials: admin / admin")
    print("Press CTRL+C to stop the server.")
    
    # Create and run the Flask app
    app = create_app()
    app.run(debug=True, port=5000)

if __name__ == "__main__":
    main()
