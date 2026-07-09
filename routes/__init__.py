"""
Routes package for Deezer Eclipse Addon
"""

from . import manifest
from . import stream
from . import search
from . import catalog


def register_all_routes(app, api_key, dz, deezer_api, streaming_session):
    """Register all application routes"""
    manifest.register_routes(app, api_key)
    stream.register_routes(app, api_key, dz, deezer_api, streaming_session)
    search.register_routes(app, api_key, dz, deezer_api)
    catalog.register_routes(app, api_key, dz, deezer_api)
