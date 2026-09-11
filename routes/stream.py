"""
Streaming routes for Eclipse Music addon
"""

import logging
from flask import request, jsonify, Response
import requests
from helpers import (
    build_track_search_queries,
    validate_token,
    get_request_base_url,
    is_track_streamable,
    is_exact_recording,
    normalize_isrc,
    parse_byte_range,
    simplify_user_agent,
)
from crypto import generate_decrypted

logger = logging.getLogger(__name__)


def resolve_deezer_isrc(dz, deezer_api, isrc):
    """Resolve an ISRC only when Deezer returns a streamable exact recording."""
    normalized_isrc = normalize_isrc(isrc)
    if not normalized_isrc:
        return None

    response = requests.get(f'{deezer_api}/track/isrc:{normalized_isrc}', timeout=3)
    if response.status_code != 200:
        return None

    track = response.json()
    returned_isrc = normalize_isrc(track.get('isrc', ''))
    if returned_isrc and returned_isrc != normalized_isrc:
        return None

    track_id = track.get('id')
    if not track_id:
        return None

    streamable, _ = is_track_streamable(dz, track_id)
    return track if streamable else None


def build_resolved_item(track):
    """Build the track identity object expected by Eclipse's resolve endpoint."""
    album = track.get('album', {})
    item = {
        'id': str(track.get('id')),
        'type': 'track',
        'title': track.get('title', ''),
        'artist': track.get('artist', {}).get('name', ''),
        'album': album.get('title', ''),
        'durationMs': int(track.get('duration', 0)) * 1000,
        'artworkURL': album.get('cover_big', album.get('cover_medium', ''))
    }
    isrc = normalize_isrc(track.get('isrc', ''))
    if isrc:
        item['isrc'] = isrc
    return item


def register_routes(app, api_key, dz, deezer_api, streaming_session):
    """Register streaming routes"""

    @app.route('/<token>/resolve-isrc')
    def resolve_isrc(token):
        """Resolve an exact ISRC to a streamable Deezer track ID."""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401

        raw_isrc = request.args.get('isrc', '')
        normalized_isrc = normalize_isrc(raw_isrc)
        if not normalized_isrc:
            return jsonify({'error': 'Valid ISRC required'}), 400

        try:
            track = resolve_deezer_isrc(dz, deezer_api, normalized_isrc)
            track_id = str(track['id']) if track else None
            logger.debug(f"[Resolve] ISRC {normalized_isrc} -> {track_id or 'null'}")
            return jsonify({'trackId': track_id})
        except requests.RequestException as error:
            logger.warning(f"[Resolve] Deezer ISRC lookup failed: {error}")
            return jsonify({'trackId': None})

    @app.route('/<token>/resolve')
    def resolve_recording(token):
        """Resolve a recording identity to a streamable Deezer item."""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401

        raw_isrc = request.args.get('isrc', '')
        title = request.args.get('title', '').strip()
        artist = request.args.get('artist', '').strip()
        duration_ms = request.args.get('durationMs')

        try:
            if raw_isrc:
                normalized_isrc = normalize_isrc(raw_isrc)
                if not normalized_isrc:
                    return jsonify({'error': 'Invalid ISRC'}), 400
                track = resolve_deezer_isrc(dz, deezer_api, normalized_isrc)
                return jsonify({'item': build_resolved_item(track) if track else None})

            if not title or not artist:
                return jsonify({'error': 'title and artist required'}), 400

            search_query = f'{artist} {title}'
            seen_track_ids = set()
            for query_variant in build_track_search_queries(search_query):
                response = requests.get(
                    f'{deezer_api}/search/track',
                    params={'q': query_variant, 'limit': 25},
                    timeout=3
                )
                if response.status_code != 200:
                    continue

                for track in response.json().get('data', []):
                    track_id = track.get('id')
                    if not track_id or track_id in seen_track_ids:
                        continue
                    seen_track_ids.add(track_id)
                    if not is_exact_recording(track, title, artist, duration_ms):
                        continue
                    streamable, _ = is_track_streamable(dz, track_id)
                    if streamable:
                        logger.debug(f"[Resolve] {title} - {artist} -> {track_id}")
                        return jsonify({'item': build_resolved_item(track)})

            logger.debug(f"[Resolve] {title} - {artist} -> null")
            return jsonify({'item': None})
        except requests.RequestException as error:
            logger.warning(f"[Resolve] Deezer lookup failed: {error}")
            return jsonify({'item': None})
    
    @app.route('/<token>/applemusic/warm', methods=['POST', 'GET'])
    def applemusic_warm(token):
        """Warm/preload ISRC to Deezer track mapping (cache warming endpoint)"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401

        # Get ISRC from query params or JSON body
        payload = request.get_json(silent=True) or {}
        isrc = request.args.get('isrc', '') or payload.get('isrc', '')
        
        if not isrc:
            return jsonify({'error': 'ISRC required'}), 400
        
        try:
            # Quick ISRC resolution check (simplified version without fallbacks)
            track_response = requests.get(f'{deezer_api}/track/isrc:{isrc}', timeout=3)
            if track_response.status_code == 200:
                track_data = track_response.json()
                deezer_track_id = track_data.get('id')
                
                if deezer_track_id:
                    # Verify it's streamable
                    streamable, title = is_track_streamable(dz, deezer_track_id)
                    if streamable:
                        logger.debug(f"Warm: ISRC {isrc} -> Track {deezer_track_id} ({title[:40]})")
                        return jsonify({'status': 'ok', 'trackId': str(deezer_track_id)})
            
            logger.debug(f"Warm: ISRC {isrc} not available")
            return jsonify({'status': 'unavailable'}), 200
            
        except Exception as e:
            logger.error(f"Warm error: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/<token>/applemusic/stream')
    def applemusic_stream(token):
        """Resolve ISRC or Apple Music trackId to Deezer track with automatic fallbacks"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        isrc = request.args.get('isrc', '')
        apple_track_id = request.args.get('trackId', '')
        
        if not isrc and not apple_track_id:
            return jsonify({'error': 'ISRC or trackId required'}), 400
        
        try:
            deezer_track_id = None
            track_title = "Unknown"
            method = "unknown"
            
            # METHOD 1: Direct ISRC resolution in Deezer (if ISRC provided)
            if isrc:
                try:
                    track_response = requests.get(f'{deezer_api}/track/isrc:{isrc}', timeout=3)
                    if track_response.status_code == 200:
                        track_data = track_response.json()
                        candidate_id = track_data.get('id')
                        if candidate_id:
                            streamable, title = is_track_streamable(dz, candidate_id)
                            if streamable:
                                deezer_track_id = candidate_id
                                track_title = title
                                method = "Direct ISRC"
                                logger.debug(f"Direct ISRC found: {deezer_track_id}")
                except (requests.RequestException, TypeError, ValueError) as error:
                    logger.debug(f"Direct ISRC lookup failed: {error}")
            
            # METHOD 2: Apple Music iTunes API resolution (if direct ISRC failed)
            if not deezer_track_id and apple_track_id:
                logger.debug(f"Direct ISRC failed, trying Apple Music API for trackId {apple_track_id}")
                try:
                    # Try with country parameter (US is most common)
                    itunes_url = f'https://itunes.apple.com/lookup?id={apple_track_id}&country=US&entity=song'
                    itunes_response = requests.get(itunes_url, timeout=5)
                    
                    if itunes_response.status_code == 200:
                        itunes_data = itunes_response.json()
                        results = itunes_data.get('results', [])
                        result_count = itunes_data.get('resultCount', 0)
                        
                        logger.debug(f"Apple Music API: {result_count} results")
                        
                        if results and len(results) > 0:
                            track_info = results[0]
                            title = track_info.get('trackName', '')
                            artist = track_info.get('artistName', '')
                            
                            logger.debug(f"Apple Music response: kind={track_info.get('kind', 'N/A')}, title={title}, artist={artist}")
                            
                            if title and artist:
                                logger.debug(f"Apple Music found: {title} by {artist}")
                                
                                # Search in Deezer by title/artist with higher limit
                                search_query = f"{title} {artist}"
                                
                                # Normalize query for better Deezer API matching
                                # Deezer API is strict: "Remaster" != "Remastered"
                                normalized_query = search_query.replace('Remastered', 'Remaster').replace('remastered', 'remaster')
                                if normalized_query != search_query:
                                    logger.debug(f"Query normalized: '{search_query}' -> '{normalized_query}'")
                                
                                search_url = f'{deezer_api}/search/track?q={normalized_query}&limit=50'
                                search_response = requests.get(search_url, timeout=3)
                                
                                if search_response.status_code == 200:
                                    results = search_response.json().get('data', [])
                                    logger.debug(f"Deezer search found {len(results)} candidates")
                                    
                                    # Test ALL results to find a streamable one
                                    tested = 0
                                    for track in results:
                                        track_id = track.get('id')
                                        if track_id:
                                            tested += 1
                                            streamable, track_title_check = is_track_streamable(dz, track_id)
                                            if streamable:
                                                deezer_track_id = track_id
                                                track_title = track_title_check
                                                method = "AppleMusic"
                                                logger.debug(f"Apple Music resolved: {isrc} -> track {deezer_track_id} (tested {tested}/{len(results)} candidates)")
                                                break
                                            else:
                                                logger.debug(f"Candidate {track_id} not streamable")
                                    
                                    if not deezer_track_id:
                                        logger.debug(f"Apple Music: found {title} but no streamable version in {tested} Deezer results")
                                else:
                                    logger.debug(f"Deezer search failed with status {search_response.status_code}")
                            else:
                                logger.debug(f"Apple Music: missing title or artist")
                        else:
                            logger.debug(f"Apple Music: no track info found for ID {apple_track_id}")
                    else:
                        logger.debug(f"Apple Music API returned {itunes_response.status_code}")
                except Exception as e:
                    logger.debug(f"Apple Music error: {e}")
            
            if not deezer_track_id:
                identifier = isrc if isrc else f"trackId {apple_track_id}"
                logger.info(f"{identifier} not found")
                return jsonify({'error': 'Track not available'}), 404
            
            # Return proxy URL for streamable track
            base_url = get_request_base_url()
            proxy_url = f"{base_url}/{token}/proxy/stream/{deezer_track_id}"
            
            identifier = isrc if isrc else f"trackId {apple_track_id}"
            logger.debug(f"{identifier} -> Track {deezer_track_id} ({method}) {track_title[:40]}")
            return jsonify({'url': proxy_url})
            
        except Exception as e:
            logger.error(f"AppleMusic stream error: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/<token>/stream', methods=['GET', 'HEAD', 'OPTIONS'])
    def deezer_stream(token):
        """Stream Deezer track by trackId (Eclipse web client) - returns URL JSON"""
        # Handle CORS preflight
        if request.method == 'OPTIONS':
            headers = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Max-Age': '3600'
            }
            return Response(status=200, headers=headers)
        
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        track_id = request.args.get('trackId', '')
        if not track_id:
            return jsonify({'error': 'trackId required'}), 400
        
        # Return proxy URL (same format as applemusic/stream)
        base_url = get_request_base_url()
        proxy_url = f"{base_url}/{token}/stream/{track_id}"
        
        logger.debug(f"[Stream] Deezer track {track_id} -> {proxy_url}")
        return jsonify({'url': proxy_url})

    @app.route('/<token>/stream/<track_id>', methods=['GET', 'OPTIONS'])
    def resolve_stream(token, track_id):
        """Resolve a track ID to a playable audio source."""
        if request.method == 'OPTIONS':
            return Response(status=200, headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': request.headers.get(
                    'Access-Control-Request-Headers',
                    'Content-Type, Accept'
                ),
                'Access-Control-Max-Age': '3600'
            })

        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401

        try:
            int(track_id)
        except ValueError:
            return jsonify({'error': 'Invalid track ID'}), 400

        base_url = get_request_base_url()
        audio_url = f"{base_url}/{token}/proxy/stream/{track_id}"
        logger.debug(f"[Stream] Resolving track {track_id} -> {audio_url}")
        response = jsonify({
            'url': audio_url,
            'format': 'mp3',
            'quality': '128kbps',
            'codec': 'mp3',
            'container': 'mp3',
            'manifest': 'none'
        })
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
        return response

    @app.route('/<token>/proxy/stream/<track_id>', methods=['GET', 'HEAD', 'OPTIONS'])
    def proxy_stream(token, track_id):
        """Stream Deezer track with live Blowfish decryption (no temp file)"""
        # Handle OPTIONS preflight for CORS
        if request.method == 'OPTIONS':
            return Response(status=200, headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
                'Access-Control-Allow-Headers': request.headers.get(
                    'Access-Control-Request-Headers',
                    'Range, Content-Type, Accept'
                ),
                    'Access-Control-Max-Age': '3600',
                    'Cross-Origin-Resource-Policy': 'cross-origin'
            })

        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401

        if not track_id.isdigit():
            return jsonify({'error': 'Invalid track ID'}), 400
        
        logger.debug(f"Streaming: track {track_id} (method: {request.method})")
        logger.debug(f"Client: {simplify_user_agent(request.headers.get('User-Agent', ''))}")
        logger.debug(f"Range: {request.headers.get('Range', 'None')}")
        
        try:
            # Get track metadata from Deezer
            track_info = dz.gw.get_track(int(track_id))
            if not track_info:
                return jsonify({'error': 'Track not found'}), 404
            
            track_title = track_info.get('SNG_TITLE', 'Unknown')
            artist = track_info.get('ART_NAME', 'Unknown')
            track_name = f"{track_title} - {artist}"
            logger.debug(f"Track: {track_name}")
            
            # Get track token for download URL generation
            track_token = track_info.get('TRACK_TOKEN')
            if not track_token:
                return jsonify({'error': 'No track token'}), 404
            
            logger.debug(f"Getting stream URL (MP3_128)")
            
            # Get encrypted stream URL (MP3_128 for free accounts)
            download_url = None
            try:
                urls = dz.get_tracks_url([track_token], "MP3_128")
                
                # Validate result
                if urls and len(urls) > 0 and urls[0]:
                    url = urls[0]
                    # Check if it's a valid string URL (not an exception object)
                    if isinstance(url, str) and url.startswith('http'):
                        download_url = url
                        logger.debug(f"Stream URL: {download_url[:80]}...")
                    else:
                        logger.debug(f"Invalid URL type: {type(url).__name__}")
                else:
                    logger.debug(f"No URLs returned")
                        
            except Exception as e:
                # get_tracks_url can raise WrongGeolocation or other exceptions
                logger.debug(f"get_tracks_url failed: {type(e).__name__} - {e}")
                pass
            
            # No fallback - return error if stream not available
            if not download_url:
                logger.debug(f"Track {track_id} geo-restricted, no stream available")
                return jsonify({'error': 'No stream available (geo-restricted)'}), 451
            
            # Get Content-Length from Deezer (ALWAYS, for iOS compatibility)
            # iOS needs Content-Length to enable seeking/range requests
            content_length = None
            try:
                head_response = streaming_session.head(download_url, timeout=1)
                if head_response.status_code == 200:
                    content_length = head_response.headers.get('Content-Length')
                    if content_length:
                        logger.debug(f"[Stream] Content-Length: {content_length} bytes")
            except Exception as e:
                logger.debug(f"[Stream] Could not get Content-Length: {e}")
            
            # Parse Range header for partial content requests
            range_header = request.headers.get('Range')
            
            # Parse Range header (iOS uses this to calculate duration)
            start_byte = 0
            end_byte = None
            is_range_request = False
            
            if range_header and content_length:
                try:
                    start_byte, end_byte = parse_byte_range(range_header, content_length)
                    is_range_request = True
                    logger.debug(f"Range request: bytes {start_byte}-{end_byte}/{content_length}")
                except (TypeError, ValueError) as error:
                    logger.debug(f"Rejected Range header: {error}")
                    return Response(status=416, headers={
                        'Content-Range': f'bytes */{content_length}',
                        'Accept-Ranges': 'bytes',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Expose-Headers': 'Content-Length, Content-Range',
                        'Cross-Origin-Resource-Policy': 'cross-origin'
                    })
            
            # Handle HEAD request (iOS checks file existence/size)
            if request.method == 'HEAD':
                logger.debug(f"HEAD request - returning headers only")
                headers = {
                    'Content-Type': 'audio/mpeg',
                    'Accept-Ranges': 'bytes',
                    'Cache-Control': 'public, max-age=3600',
                    'X-Content-Type-Options': 'nosniff',
                    'Access-Control-Allow-Origin': '*',
                        'Access-Control-Expose-Headers': 'Content-Length, Content-Range',
                        'Cross-Origin-Resource-Policy': 'cross-origin'
                }
                status_code = 200
                if is_range_request:
                    status_code = 206
                    headers['Content-Length'] = str(end_byte - start_byte + 1)
                    headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{content_length}'
                elif content_length:
                    headers['Content-Length'] = content_length
                return Response(status=status_code, headers=headers)
            
            logger.debug(f"Starting live decryption...")
            
            # Build response headers
            headers = {
                'Content-Type': 'audio/mpeg',
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'public, max-age=3600',
                'X-Content-Type-Options': 'nosniff',
                'Access-Control-Allow-Origin': '*',
                    'Access-Control-Expose-Headers': 'Content-Length, Content-Range',
                    'Cross-Origin-Resource-Policy': 'cross-origin'
            }
            
            # Set appropriate status code and headers for range requests
            status_code = 200
            if is_range_request:
                status_code = 206  # Partial Content
                range_length = end_byte - start_byte + 1
                headers['Content-Length'] = str(range_length)
                headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{content_length}'
                logger.debug(f"[Stream] 206 Partial Content: {range_length} bytes")
                # Log only significant streams (not test ranges)
                if range_length > 100000:  # > 100KB = real stream
                    logger.info(f"Track {track_id} requested: {track_name[:40]}")
            else:
                # Set Content-Length for full streams (Blowfish ECB preserves file size)
                # iOS needs this to enable seeking and range requests
                if content_length:
                    headers['Content-Length'] = content_length
                    logger.debug(f"[Stream] 200 OK: Content-Length={content_length}")
                else:
                    logger.debug(f"[Stream] 200 OK: streaming without Content-Length (chunked transfer)")
                logger.info(f"Track {track_id} requested: {track_name[:40]}")
            
            # Capture user_agent before creating generator (request context may not be available later)
            
            # Log streaming completion after response
            def generate_with_completion_log():
                for chunk in generate_decrypted(dz, streaming_session, download_url, track_id, start_byte, end_byte, track_name):
                    yield chunk
                # Log completion after all chunks sent
                logger.debug(f"Track {track_id} streamed: {track_name[:40]}")
            
            return Response(
                generate_with_completion_log(),
                status=status_code,
                headers=headers
            )
            
        except Exception as e:
            logger.error(f"Stream error track {track_id}: {e}")
            logger.debug(f"Traceback: {e}")
            return jsonify({'error': str(e)}), 500

