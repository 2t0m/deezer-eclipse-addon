"""
Manifest route for Eclipse Music addon
"""

from flask import jsonify
from helpers import validate_token


def register_routes(app, api_key):
    """Register manifest route"""
    
    @app.route('/<token>/manifest.json')
    def manifest(token):
        """Addon manifest - describes capabilities to Eclipse Music"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        return jsonify({
            'id': 'com.deezer.eclipse',
            'name': 'Deezer',
            'version': '1.0.1',
            'description': 'Stream full tracks from Deezer',
            'icon': 'https://e-cdns-images.dzcdn.net/images/common/deezer-logo-2019.svg',
            'resources': ['stream'],
            'types': ['track'],
            'contentType': 'music'
        })
