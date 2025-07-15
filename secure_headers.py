# secure_headers.py
"""
This module sets secure HTTP headers for Flask apps, including HSTS, CSP, X-Frame-Options, etc.
Usage: import and call `init_secure_headers(app)` after creating your Flask app.
"""

def init_secure_headers(app):
    @app.after_request
    def set_secure_headers(response):
        # Strict-Transport-Security (HSTS)
        response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Referrer policy
        response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
        # Content Security Policy (CSP) - adjust as needed
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline'; "
            "object-src 'none'; "
            "frame-ancestors 'self'; "
            "frame-src 'self' https://calendar.google.com;"
        )
        return response
