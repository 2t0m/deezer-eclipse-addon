"""
Helper functions for Deezer Eclipse Addon
"""

import logging
from flask import request

logger = logging.getLogger(__name__)


def validate_token(token, api_key):
    """Validate API token from URL path"""
    if not api_key:
        return True  # No security if API_KEY not configured
    
    if token != api_key:
        logger.warning(f"Unauthorized: token {token[:10]}... from {request.remote_addr}")
        return False
    
    return True


def is_track_streamable(dz, track_id):
    """Check if a track ID is streamable (not geo-blocked)"""
    try:
        track_info = dz.gw.get_track(int(track_id))
        if not track_info:
            return False, None
        
        track_token = track_info.get('TRACK_TOKEN')
        if not track_token:
            return False, None
        
        urls = dz.get_tracks_url([track_token], "MP3_128")
        if urls and urls[0] and isinstance(urls[0], str) and urls[0].startswith('http'):
            track_title = f"{track_info.get('SNG_TITLE', 'Unknown')} - {track_info.get('ART_NAME', 'Unknown')}"
            return True, track_title
        return False, None
    except:
        return False, None
