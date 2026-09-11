"""
Helper functions for Deezer Eclipse Addon
"""

import logging
import re
import unicodedata
from flask import request

logger = logging.getLogger(__name__)

ISRC_PATTERN = re.compile(r'^[A-Z0-9]{12}$')
NEUTRAL_VERSION_PATTERN = re.compile(
    r'\s*[\(\[]\s*(?:radio|single|album|original)\s+(?:edit|version)\s*[\)\]]\s*$',
    re.IGNORECASE
)


def simplify_user_agent(user_agent):
    """Return a compact client and platform label for logs."""
    debrid = re.search(r'(DebridMusic(?:-iOS)?/[\w.]+)', user_agent or '')
    if debrid:
        client = debrid.group(1)
        if '-iOS/' not in client and ('CFNetwork/' in user_agent or 'Darwin/' in user_agent):
            return f'{client} iOS'
        return client

    chrome = re.search(r'(?:Chrome|CriOS)/(\d+)', user_agent or '')
    if chrome:
        platform = 'Android' if 'Android' in user_agent else 'Desktop'
        return f'Chrome/{chrome.group(1)} {platform}'

    if (user_agent or '').startswith('Werkzeug/'):
        return 'StartupCheck'
    return 'Other'


def normalize_isrc(value):
    """Return a canonical ISRC, or an empty string when it is invalid."""
    normalized = re.sub(r'[^A-Za-z0-9]', '', value or '').upper()
    return normalized if ISRC_PATTERN.fullmatch(normalized) else ''


def normalize_recording_text(value):
    """Normalize metadata for conservative title and artist comparisons."""
    ascii_value = unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', ascii_value.lower()).split())


def strip_neutral_version(value):
    """Remove a trailing edition label that does not identify a remix or live take."""
    return NEUTRAL_VERSION_PATTERN.sub('', value or '').strip()


def build_track_search_queries(query):
    """Return the literal query and a conservative edition-free fallback."""
    fallback = strip_neutral_version(query)
    return [query] if fallback == query else [query, fallback]


def is_exact_recording(track, title, artist, duration_ms=None, tolerance_ms=3000):
    """Check whether Deezer metadata confidently identifies the requested recording."""
    track_artist = track.get('artist', {}).get('name', '')
    track_title = normalize_recording_text(strip_neutral_version(track.get('title', '')))
    requested_title = normalize_recording_text(strip_neutral_version(title))
    if track_title != requested_title:
        return False
    if normalize_recording_text(track_artist) != normalize_recording_text(artist):
        return False

    if duration_ms is None:
        return True

    try:
        requested_duration = int(duration_ms)
        track_duration = int(track.get('duration', 0)) * 1000
    except (TypeError, ValueError):
        return False

    return track_duration > 0 and abs(track_duration - requested_duration) <= tolerance_ms


def get_request_base_url():
    """Return the proxy-aware request URL without a trailing slash."""
    return request.url_root.rstrip('/')


def parse_byte_range(value, content_length):
    """Parse one HTTP byte range and return its inclusive start and end."""
    total = int(content_length)
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value or '')
    if total <= 0 or not match or not any(match.groups()):
        raise ValueError('Invalid byte range')

    start_value, end_value = match.groups()
    if not start_value:
        suffix_length = int(end_value)
        if suffix_length <= 0:
            raise ValueError('Invalid suffix range')
        return max(total - suffix_length, 0), total - 1

    start = int(start_value)
    end = int(end_value) if end_value else total - 1
    if start >= total or end < start:
        raise ValueError('Unsatisfiable byte range')
    return start, min(end, total - 1)


def validate_token(token, api_key):
    """Validate API token from URL path"""
    if not api_key:
        return True  # No security if API_KEY not configured
    
    if token != api_key:
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
    except Exception as error:
        logger.debug(f"Track {track_id} streamability check failed: {error}")
        return False, None
