"""
Deezer Eclipse Addon - Streaming addon for Eclipse Music iOS app
Streams full Deezer tracks (not 30s previews) with live Blowfish decryption
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
import os
import tempfile
from dotenv import load_dotenv
from deezer import Deezer
from deemix.settings import load as loadSettings
from deemix.utils.crypto import generateBlowfishKey, decryptChunk

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuration
DEEZER_ARL = os.getenv('DEEZER_ARL')
DEEZER_API = 'https://api.deezer.com'
API_KEY = os.getenv('API_KEY', '')

# Token validation
def validate_token(token):
    """Validate API token from URL path"""
    if not API_KEY:
        return True  # No security if API_KEY not configured
    
    if token != API_KEY:
        print(f"🚫 Unauthorized: token {token[:10]}... from {request.remote_addr}")
        return False
    
    return True

# Initialize Deezer client
dz = Deezer()
if DEEZER_ARL:
    login_success = dz.login_via_arl(DEEZER_ARL)
    print(f"🎵 Deezer login: {'✓ Success' if login_success else '✗ Failed'}")
else:
    print("⚠️  No ARL configured")

# HTTP session for streaming (reuses connections, avoids SSL handshakes)
streaming_session = requests.Session()
streaming_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

# Load deemix settings
settings = loadSettings()
settings['downloadLocation'] = tempfile.gettempdir()
settings['maxBitrate'] = "3"  # MP3_128 for free accounts
settings['saveArtwork'] = False
settings['createCDFolder'] = False
settings['createArtistFolder'] = False
settings['createAlbumFolder'] = False

print(f"📁 Download location: {settings['downloadLocation']}")

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/<token>/manifest.json')
def manifest(token):
    """Addon manifest - describes capabilities to Eclipse Music"""
    if not validate_token(token):
        return jsonify({'error': 'Unauthorized'}), 401
    
    return jsonify({
        'id': 'com.deezer.eclipse',
        'name': 'Deezer',
        'version': '1.0.1',
        'description': 'Stream full tracks from Deezer',
        'icon': 'https://e-cdns-images.dzcdn.net/images/common/deezer-logo-2019.svg',
        'resources': ['search', 'stream'],
        'types': ['track'],
        'contentType': 'music'
    })

@app.route('/<token>/search')
def search(token):
    """Search tracks on Deezer with ISRC codes"""
    if not validate_token(token):
        return jsonify({'error': 'Unauthorized'}), 401
    
    query = request.args.get('q', '')
    if not query:
        return jsonify({'tracks': []})
    
    print(f"🔍 Searching: {query}")
    
    try:
        # Search tracks on Deezer
        response = requests.get(f'{DEEZER_API}/search/track', params={'q': query, 'limit': 20})
        tracks_data = response.json()
        
        tracks = []
        for track in tracks_data.get('data', []):
            track_obj = {
                'id': str(track['id']),
                'title': track['title'],
                'artist': track['artist']['name'],
                'album': track['album']['title'] if 'album' in track else '',
                'duration': track['duration'],
                'artworkURL': track['album']['cover_big'] if 'album' in track else '',
                'format': 'mp3'
            }
            # ISRC codes are critical for Eclipse Music stream resolution
            if 'isrc' in track and track['isrc']:
                track_obj['isrc'] = track['isrc']
            tracks.append(track_obj)
        
        print(f"✓ Found {len(tracks)} tracks")
        return jsonify({'tracks': tracks})
        
    except Exception as e:
        print(f"⚠ Search error: {e}")
        return jsonify({'tracks': []})

@app.route('/<token>/applemusic/stream')
def applemusic_stream(token):
    """Resolve ISRC to Deezer track and return proxy stream URL"""
    if not validate_token(token):
        return jsonify({'error': 'Unauthorized'}), 401
    
    track_id = request.args.get('trackId', '')
    quality = request.args.get('quality', 'LOSSLESS')
    isrc = request.args.get('isrc', '')
    
    print(f"🍎 Stream request: trackId={track_id}, quality={quality}, isrc={isrc}")
    
    if not isrc:
        return jsonify({'error': 'ISRC required'}), 400
    
    try:
        # Resolve ISRC to Deezer track ID
        track_response = requests.get(f'{DEEZER_API}/track/isrc:{isrc}')
        
        if track_response.status_code != 200:
            print(f"✗ ISRC {isrc} not found")
            return jsonify({'error': 'Track not found'}), 404
        
        track_data = track_response.json()
        deezer_track_id = track_data.get('id')
        
        if not deezer_track_id:
            return jsonify({'error': 'Invalid track data'}), 404
        
        print(f"✓ ISRC {isrc} → Deezer {deezer_track_id}")
        
        # Get track info for debugging
        try:
            track_info = dz.gw.get_track(int(deezer_track_id))
            if track_info:
                print(f"→ Title: {track_info.get('SNG_TITLE', 'Unknown')} - {track_info.get('ART_NAME', 'Unknown')}")
        except Exception as e:
            print(f"⚠ Could not fetch track info: {e}")
        
        # Return proxy URL (token embedded for security)
        # Use request.host to build URL dynamically for each server
        # Force HTTPS for security (required by iOS apps)
        base_url = f"https://{request.host}"
        proxy_url = f"{base_url}/{token}/proxy/stream/{deezer_track_id}"
        print(f"✓ Proxy URL: {proxy_url}")
        
        return jsonify({'url': proxy_url})
        
    except Exception as e:
        print(f"⚠ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/<token>/proxy/stream/<track_id>', methods=['GET', 'HEAD', 'OPTIONS'])
def proxy_stream(token, track_id):
    """Stream Deezer track with live Blowfish decryption (no temp file)"""
    if not validate_token(token):
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Handle OPTIONS preflight for CORS
    if request.method == 'OPTIONS':
        return Response(status=200, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': '*'
        })
    
    print(f"🎵 Streaming: track {track_id} (method: {request.method})")
    print(f"→ User-Agent: {request.headers.get('User-Agent', 'Unknown')}")
    print(f"→ Range: {request.headers.get('Range', 'None')}")
    
    try:
        # Get track metadata from Deezer
        track_info = dz.gw.get_track(int(track_id))
        if not track_info:
            return jsonify({'error': 'Track not found'}), 404
        
        track_title = track_info.get('SNG_TITLE', 'Unknown')
        artist = track_info.get('ART_NAME', 'Unknown')
        print(f"→ Track: {track_title} - {artist}")
        
        # Get track token for download URL generation
        track_token = track_info.get('TRACK_TOKEN')
        if not track_token:
            return jsonify({'error': 'No track token'}), 404
        
        # Get encrypted stream URL (MP3_128 for free accounts)
        print(f"→ Getting stream URL (MP3_128)")
        try:
            urls = dz.get_tracks_url([track_token], "MP3_128")
        except Exception as e:
            # Fallback to 30s preview if full track unavailable
            print(f"✗ Full track failed: {e}, using preview")
            preview_url = track_info.get('TRACK_PREVIEW')
            if preview_url:
                return Response(
                    streaming_session.get(preview_url, stream=True, timeout=30).iter_content(chunk_size=131072),
                    headers={'Content-Type': 'audio/mpeg', 'Cache-Control': 'public, max-age=3600'}
                )
            return jsonify({'error': 'No stream available'}), 404
        
        if not urls or not urls[0]:
            return jsonify({'error': 'No stream available'}), 404
        
        download_url = urls[0]
        print(f"→ Stream URL: {download_url[:80]}...")
        
        # Get Content-Length from Deezer for better iOS compatibility
        content_length = None
        try:
            head_response = streaming_session.head(download_url, timeout=5)
            if head_response.status_code == 200:
                content_length = head_response.headers.get('Content-Length')
                if content_length:
                    print(f"→ Content-Length: {content_length} bytes")
        except Exception as e:
            print(f"⚠ Could not get Content-Length: {e}")
        
        # Handle HEAD request (iOS checks file existence/size)
        if request.method == 'HEAD':
            print(f"→ HEAD request - returning headers only")
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
        
        print(f"→ Starting live decryption...")
        
        # Generate track-specific Blowfish decryption key
        blowfish_key = generateBlowfishKey(str(track_id))
        
        def generate_decrypted():
            """
            Deezer Blowfish decryption algorithm:
            - Encrypted stream is split into 2048-byte chunks
            - Every 3rd chunk (0, 3, 6, 9...) is encrypted with Blowfish ECB
            - Other chunks are plain MP3 data
            
            Optimizations:
            - Download in 64KB chunks from Deezer (reduces network overhead)
            - Yield in 128KB chunks to Flask (reduces HTTP overhead)
            - Pre-buffer 256KB before first yield (smooth playback start)
            - Use bytearray for efficient memory operations
            """
            response = streaming_session.get(download_url, stream=True, timeout=30)
            
            if response.status_code != 200:
                print(f"✗ Download failed: {response.status_code}")
                return
            
            # Configuration
            decrypt_chunk_size = 2048      # Deezer encryption chunk size (fixed)
            download_chunk_size = 65536    # Download 64KB at a time
            yield_size = 65536             # Yield 64KB chunks (faster first byte for iOS)
            pre_buffer_size = 32768        # Pre-buffer 32KB (enough for iOS format detection)
            
            # Buffers
            chunk_index = 0
            buffer = b''
            output_buffer = bytearray()
            total_yielded = 0
            
            print(f"→ Buffer config: download={download_chunk_size}B, yield={yield_size}B, prebuffer={pre_buffer_size}B")
            
            # Stream and decrypt
            for chunk in response.iter_content(chunk_size=download_chunk_size):
                if not chunk:
                    break
                
                buffer += chunk
                
                # Process 2048-byte chunks (Deezer requirement)
                while len(buffer) >= decrypt_chunk_size:
                    current_chunk = buffer[:decrypt_chunk_size]
                    buffer = buffer[decrypt_chunk_size:]
                    
                    # Decrypt every 3rd chunk (Deezer encryption pattern)
                    if chunk_index % 3 == 0:
                        try:
                            decrypted = decryptChunk(blowfish_key, current_chunk)
                            output_buffer.extend(decrypted)
                        except Exception as e:
                            print(f"⚠ Decrypt error chunk {chunk_index}: {e}")
                            output_buffer.extend(current_chunk)
                    else:
                        output_buffer.extend(current_chunk)
                    
                    chunk_index += 1
                    
                    # Pre-buffer before first yield (smooth start)
                    if total_yielded == 0 and len(output_buffer) < pre_buffer_size:
                        continue
                    
                    # Yield in 128KB chunks
                    if len(output_buffer) >= yield_size:
                        yield bytes(output_buffer)
                        total_yielded += len(output_buffer)
                        output_buffer = bytearray()
            
            # Flush remaining data
            if buffer:
                output_buffer.extend(buffer)
            if output_buffer:
                yield bytes(output_buffer)
                total_yielded += len(output_buffer)
            
            print(f"✓ Streamed {chunk_index} chunks ({total_yielded} bytes)")
        
        headers = {
            'Content-Type': 'audio/mpeg',
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'public, max-age=3600',
            'X-Content-Type-Options': 'nosniff',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Expose-Headers': 'Content-Length, Content-Range'
        }
        
        # Add Content-Length if available (helps iOS with buffering)
        if content_length:
            headers['Content-Length'] = content_length
        
        print(f"→ Sending stream with headers: {headers}")
        return Response(generate_decrypted(), headers=headers)
        
    except Exception as e:
        print(f"⚠ Streaming error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/<token>/applemusic/warm', methods=['POST'])
def applemusic_warm(token):
    """Warmup endpoint for Eclipse Music pre-loading"""
    if not validate_token(token):
        return jsonify({'error': 'Unauthorized'}), 401
    
    print(f"🔥 Warmup request")
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
