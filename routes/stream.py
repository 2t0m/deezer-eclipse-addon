"""
Streaming routes for Eclipse Music addon
"""

import logging
from flask import request, jsonify, Response
import requests
from helpers import validate_token, is_track_streamable
from crypto import generate_decrypted

logger = logging.getLogger(__name__)


def register_routes(app, api_key, dz, deezer_api, streaming_session):
    """Register streaming routes"""
    
    @app.route('/<token>/applemusic/warm', methods=['POST', 'GET'])
    def applemusic_warm(token):
        """Warm/preload ISRC to Deezer track mapping (cache warming endpoint)"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        # Get ISRC from query params or JSON body
        isrc = request.args.get('isrc', '') or request.json.get('isrc', '') if request.json else ''
        
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
                except:
                    pass
            
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
            base_url = f"https://{request.host}"
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
        base_url = f"https://{request.host}"
        proxy_url = f"{base_url}/{token}/proxy/stream/{track_id}"
        
        logger.debug(f"[Stream] Deezer track {track_id} -> {proxy_url}")
        return jsonify({'url': proxy_url})
    
    @app.route('/<token>/proxy/stream/<track_id>', methods=['GET', 'HEAD', 'OPTIONS'])
    def proxy_stream(token, track_id):
        """Stream Deezer track with live Blowfish decryption (no temp file)"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        # Handle OPTIONS preflight for CORS
        if request.method == 'OPTIONS':
            return Response(status=200, headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
                'Access-Control-Allow-Headers': '*'
            })
        
        logger.debug(f"Streaming: track {track_id} (method: {request.method})")
        logger.debug(f"User-Agent: {request.headers.get('User-Agent', 'Unknown')}")
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
            
            # Get Content-Length from Deezer for better iOS compatibility
            # Only fetch if Range request (saves ~500ms-2s on regular streams)
            content_length = None
            range_header = request.headers.get('Range')
            
            if range_header:
                try:
                    head_response = streaming_session.head(download_url, timeout=1)  # Reduced from 5s to 1s
                    if head_response.status_code == 200:
                        content_length = head_response.headers.get('Content-Length')
                        if content_length:
                            logger.debug(f"Content-Length: {content_length} bytes")
                except Exception as e:
                    logger.debug(f"Could not get Content-Length: {e}")
            
            # Parse Range header (iOS uses this to calculate duration)
            start_byte = 0
            end_byte = None
            is_range_request = False
            
            if range_header and content_length:
                is_range_request = True
                try:
                    # Parse "bytes=start-end" or "bytes=start-"
                    range_str = range_header.replace('bytes=', '')
                    if '-' in range_str:
                        parts = range_str.split('-')
                        start_byte = int(parts[0]) if parts[0] else 0
                        end_byte = int(parts[1]) if parts[1] else int(content_length) - 1
                    else:
                        start_byte = int(range_str)
                        end_byte = int(content_length) - 1
                    
                    # Clamp to file size
                    end_byte = min(end_byte, int(content_length) - 1)
                    logger.debug(f"Range request: bytes {start_byte}-{end_byte}/{content_length}")
                except Exception as e:
                    logger.debug(f"Failed to parse Range header: {e}")
                    is_range_request = False
                    start_byte = 0
                    end_byte = None
            
            # Handle HEAD request (iOS checks file existence/size)
            if request.method == 'HEAD':
                logger.debug(f"HEAD request - returning headers only")
                headers = {
                    'Content-Type': 'audio/mpeg',
                    'Accept-Ranges': 'bytes',
                    'Cache-Control': 'public, max-age=3600',
                    'X-Content-Type-Options': 'nosniff',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Expose-Headers': 'Content-Length, Content-Range'
                }
                if content_length:
                    headers['Content-Length'] = content_length
                return Response(status=200, headers=headers)
            
            logger.debug(f"Starting live decryption...")
            
            # Build response headers
            headers = {
                'Content-Type': 'audio/mpeg',
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'public, max-age=3600',
                'X-Content-Type-Options': 'nosniff',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Expose-Headers': 'Content-Length, Content-Range'
            }
            
            # Set appropriate status code and headers for range requests
            status_code = 200
            if is_range_request:
                status_code = 206  # Partial Content
                range_length = end_byte - start_byte + 1
                headers['Content-Length'] = str(range_length)
                headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{content_length}'
                logger.debug(f"206 Partial Content: {range_length} bytes")
                # Log only significant streams (not test ranges)
                if range_length > 100000:  # > 100KB = real stream
                    logger.info(f"Track {track_id} requested: {track_name[:40]}")
            else:
                # Don't set Content-Length for full streams - decrypted size differs from encrypted
                # Android and other strict clients will hang if Content-Length doesn't match actual data
                logger.debug(f"200 OK: streaming without Content-Length (chunked transfer)")
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

