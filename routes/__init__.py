"""
Routes package for Deezer Eclipse Addon
"""

from . import manifest
from . import stream
from . import arl


def register_all_routes(app, api_key, dz, deezer_api, streaming_session, debug, arl_manager_factory=None):
    """Register all application routes"""
    from helpers import set_debug
    set_debug(debug)
    manifest.register_routes(app, api_key)
    stream.register_routes(app, api_key, dz, deezer_api, streaming_session)
    
    # Register ARL management routes if arl_manager_factory is provided
    if arl_manager_factory:
        arl.register_arl_route(app, api_key, dz, arl_manager_factory)
