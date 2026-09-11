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
            'version': '2.0.0',
            'description': 'Stream full tracks from Deezer. MP3 128kbps quality.',
            'icon': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0e/Deezer_New_Icon.svg/250px-Deezer_New_Icon.svg.png',
            'resources': ['stream', 'search', 'isrc', 'resolve', 'catalog'],
            'types': ['track', 'album', 'artist', 'playlist'],
            'catalogs': [
                {'id': 'charts', 'type': 'track', 'name': 'Deezer Charts'},
                {'id': 'popular-albums', 'type': 'album', 'name': 'Popular Albums'},
                {'id': 'featured-playlists', 'type': 'playlist', 'name': 'Featured Playlists'}
            ],
            'contentType': 'music'
        })
