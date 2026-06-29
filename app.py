"""
Deezer Eclipse Addon - Streaming addon for Eclipse Music iOS app
Streams full Deezer tracks (not 30s previews) with live Blowfish decryption
"""

from flask import Flask
from flask_cors import CORS
import requests
import os
import tempfile
from dotenv import load_dotenv
from deezer import Deezer
from deemix.settings import load as loadSettings

# Load environment variables
load_dotenv()

# Configuration
DEEZER_ARL = os.getenv('DEEZER_ARL')
DEEZER_API = 'https://api.deezer.com'
API_KEY = os.getenv('API_KEY', '')
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Initialize Deezer client
dz = Deezer()
if DEEZER_ARL:
    login_success = dz.login_via_arl(DEEZER_ARL)
    status = '✓ Success' if login_success else '✗ Failed'
    print(f"🎵 Deezer login: {status}", flush=True)
else:
    print("⚠️  No ARL configured", flush=True)

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

if DEBUG:
    print(f"📁 Download location: {settings['downloadLocation']}", flush=True)
    print(f"🔍 Debug mode: ENABLED", flush=True)
else:
    print(f"📊 Log mode: NORMAL (minimal)", flush=True)

# Register all routes
from routes import register_all_routes
register_all_routes(app, API_KEY, dz, DEEZER_API, streaming_session, DEBUG)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
