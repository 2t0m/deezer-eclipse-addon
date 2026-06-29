"""
Streaming routes for Eclipse Music addon
"""

from flask import request, jsonify, Response
import requests
from helpers import validate_token, is_track_streamable, log_debug, log_info
from crypto import generate_decrypted

# Track request logging cache (avoid duplicate "requested" logs)
_logged_tracks = set()


def register_routes(app, api_key, dz, deezer_api, streaming_session):
    """Register streaming routes"""
    
    @app.route('/<token>/applemusic/stream')
    def applemusic_stream(token):
        """Resolve ISRC to Deezer track with automatic fallbacks"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        isrc = request.args.get('isrc', '')
        if not isrc:
            return jsonify({'error': 'ISRC required'}), 400
        
        try:
            deezer_track_id = None
            track_title = "Unknown"
            method = "unknown"
            
            # METHOD 1: Direct ISRC resolution
            try:
                track_response = requests.get(f'{deezer_api}/track/isrc:{isrc}')
                if track_response.status_code == 200:
                    track_data = track_response.json()
                    candidate_id = track_data.get('id')
                    if candidate_id:
                        streamable, title = is_track_streamable(dz, candidate_id)
                        if streamable:
                            deezer_track_id = candidate_id
                            track_title = title
                            method = "ISRC"
                            log_debug(f"✓ Method 1 (ISRC): {deezer_track_id}")
            except:
                pass
            
            # METHOD 2: Get track info from ISRC and search by title+artist
            if not deezer_track_id:
                try:
                    # Get track metadata from ISRC (even if geo-blocked)
                    track_response = requests.get(f'{deezer_api}/track/isrc:{isrc}')
                    if track_response.status_code == 200:
                        track_data = track_response.json()
                        title = track_data.get('title', '')
                        artist = track_data.get('artist', {}).get('name', '')
                        
                        if title or artist:
                            query = f"{title} {artist}".strip()
                            search_response = requests.get(f'{deezer_api}/search/track', params={'q': query, 'limit': 20})
                            if search_response.status_code == 200:
                                tracks = search_response.json().get('data', [])
                                for track in tracks:
                                    candidate_id = track.get('id')
                                    if candidate_id:
                                        streamable, title_found = is_track_streamable(dz, candidate_id)
                                        if streamable:
                                            deezer_track_id = candidate_id
                                            track_title = title_found
                                            method = "text-search"
                                            log_debug(f"✓ Method 2 (text search \"{query[:30]}...\"): {deezer_track_id}")
                                            break
                except:
                    pass
            
            if not deezer_track_id:
                log_info(f"⚠ ISRC:{isrc} - no streamable track found")
                return jsonify({'error': 'Track not available'}), 404
            
            # Return proxy URL for streamable track
            base_url = f"https://{request.host}"
            proxy_url = f"{base_url}/{token}/proxy/stream/{deezer_track_id}"
            
            log_debug(f"🍎 ISRC:{isrc} → Track {deezer_track_id} ({method}) \"{track_title[:40]}...\"")
            return jsonify({'url': proxy_url})
            return jsonify({'url': proxy_url})
            
        except Exception as e:
            log_info(f"⚠ Stream resolution error: {e}")
            return jsonify({'error': str(e)}), 500
    
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
        
        log_debug(f"🎵 Streaming: track {track_id} (method: {request.method})")
        log_debug(f"→ User-Agent: {request.headers.get('User-Agent', 'Unknown')}")
        log_debug(f"→ Range: {request.headers.get('Range', 'None')}")
        
        try:
            # Get track metadata from Deezer
            track_info = dz.gw.get_track(int(track_id))
            if not track_info:
                return jsonify({'error': 'Track not found'}), 404
            
            track_title = track_info.get('SNG_TITLE', 'Unknown')
            artist = track_info.get('ART_NAME', 'Unknown')
            track_name = f"{track_title} - {artist}"
            log_debug(f"→ Track: {track_name}")
            
            # Get track token for download URL generation
            track_token = track_info.get('TRACK_TOKEN')
            if not track_token:
                return jsonify({'error': 'No track token'}), 404
            
            log_debug(f"→ Getting stream URL (MP3_128)")
            
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
                        log_debug(f"→ Stream URL: {download_url[:80]}...")
                    else:
                        log_debug(f"⚠ Invalid URL type: {type(url).__name__}")
                else:
                    log_debug(f"⚠ No URLs returned")
                        
            except Exception as e:
                # get_tracks_url can raise WrongGeolocation or other exceptions
                log_debug(f"⚠ get_tracks_url failed: {type(e).__name__} - {e}")
                pass
            
            # Fallback to preview if no valid stream URL
            if not download_url:
                log_info(f"Track {track_id} geo-restricted, using preview")
                preview_url = track_info.get('TRACK_PREVIEW')
                if preview_url:
                    log_debug(f"→ Preview URL: {preview_url}")
                    return Response(
                        streaming_session.get(preview_url, stream=True, timeout=30).iter_content(chunk_size=131072),
                        headers={'Content-Type': 'audio/mpeg', 'Cache-Control': 'public, max-age=3600'}
                    )
                return jsonify({'error': 'No stream available (geo-restricted)'}), 451
            
            # Get Content-Length from Deezer for better iOS compatibility
            content_length = None
            try:
                head_response = streaming_session.head(download_url, timeout=5)
                if head_response.status_code == 200:
                    content_length = head_response.headers.get('Content-Length')
                    if content_length:
                        log_debug(f"→ Content-Length: {content_length} bytes")
            except Exception as e:
                log_debug(f"⚠ Could not get Content-Length: {e}")
            
            # Parse Range header (iOS uses this to calculate duration)
            range_header = request.headers.get('Range')
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
                    log_debug(f"→ Range request: bytes {start_byte}-{end_byte}/{content_length}")
                except Exception as e:
                    log_debug(f"⚠ Failed to parse Range header: {e}")
                    is_range_request = False
                    start_byte = 0
                    end_byte = None
            
            # Handle HEAD request (iOS checks file existence/size)
            if request.method == 'HEAD':
                log_debug(f"→ HEAD request - returning headers only")
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
            
            log_debug(f"→ Starting live decryption...")
            
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
                log_debug(f"→ 206 Partial Content: {range_length} bytes")
                # Log only significant streams (not test ranges) and only once per track
                if range_length > 100000 and track_id not in _logged_tracks:  # > 100KB = real stream
                    _logged_tracks.add(track_id)
                    log_info(f"Track {track_id} requested - \"{track_name[:40]}...\"")
            elif content_length:
                headers['Content-Length'] = content_length
                log_debug(f"→ 200 OK: {content_length} bytes")
                if track_id not in _logged_tracks:
                    _logged_tracks.add(track_id)
                    log_info(f"Track {track_id} requested - \"{track_name[:40]}...\"")
            
            # Log streaming completion after response
            def generate_with_completion_log():
                for chunk in generate_decrypted(dz, streaming_session, download_url, track_id, start_byte, end_byte, track_name):
                    yield chunk
            
            return Response(
                generate_with_completion_log(),
                status=status_code,
                headers=headers
            )
            
        except Exception as e:
            log_info(f"⚠ Streaming error for track {track_id}: {e}")
            log_debug(f"Traceback: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/<token>/applemusic/warm', methods=['POST'])
    def applemusic_warm(token):
        """Warmup endpoint for Eclipse Music pre-loading"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        return jsonify({'status': 'ok'})
