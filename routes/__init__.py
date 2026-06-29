"""
Routes package for Deezer Eclipse Addon
"""

from . import manifest
from . import stream


def register_all_routes(app, api_key, dz, deezer_api, streaming_session, debug):
    """Register all application routes"""
    from helpers import set_debug
    set_debug(debug)
    manifest.register_routes(app, api_key)
    stream.register_routes(app, api_key, dz, deezer_api, streaming_session)
