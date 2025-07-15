import os
import logging
from flask import Flask, request, render_template, current_app
from werkzeug.utils import secure_filename

# Setup logging
logging.basicConfig(
    filename='upload_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def debug_file_upload():
    """Standalone function to debug file upload issues"""
    try:
        # Get current app and request from flask
        app = current_app._get_current_object()
        
        # Log app configuration
        logging.debug("App config: %s", app.config)
        logging.debug("Static folder: %s", app.static_folder)
        logging.debug("Upload folder config: %s", app.config.get('UPLOAD_FOLDER'))
        
        # Check directories
        static_path = os.path.join(app.static_folder, 'uploads', 'store_logos')
        logging.debug("Static upload path exists: %s", os.path.exists(static_path))
        if not os.path.exists(static_path):
            try:
                os.makedirs(static_path, exist_ok=True)
                logging.debug("Created directory: %s", static_path)
            except Exception as e:
                logging.error("Error creating directory: %s", str(e))
        
        # Log permissions
        try:
            logging.debug("Static path permissions: %s", oct(os.stat(app.static_folder).st_mode))
            if os.path.exists(static_path):
                logging.debug("Upload path permissions: %s", oct(os.stat(static_path).st_mode))
        except Exception as e:
            logging.error("Error checking permissions: %s", str(e))
            
        # Register this function to run on app context
        return "Debug information logged to upload_debug.log"
    except Exception as e:
        logging.error("Debug error: %s", str(e))
        return f"Error: {str(e)}"
