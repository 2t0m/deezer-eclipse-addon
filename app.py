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
from arl_manager import create_arl_manager_from_env, load_arl_from_persistent_storage

# Load environment variables
load_dotenv()

# Configuration
DEEZER_API = 'https://api.deezer.com'
API_KEY = os.getenv('API_KEY', '')
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Initialize Deezer client with auto-refresh ARL
dz = Deezer()
login_success = False

# Try to load ARL from persistent storage (Docker volume)
DEEZER_ARL = load_arl_from_persistent_storage()

# Try to login with stored ARL
if DEEZER_ARL:
    login_success = dz.login_via_arl(DEEZER_ARL)
    status = '✓ Success' if login_success else '✗ Failed'
    print(f"🎵 Deezer login: {status}", flush=True)

# If login failed, attempt auto-refresh
if not login_success:
    print(f"🔄 Login failed, attempting auto-refresh ARL...", flush=True)
    try:
        arl_manager = create_arl_manager_from_env()
        if arl_manager:
            new_arl = arl_manager.get_new_arl()
            if new_arl:
                print(f"✅ New ARL retrieved: {new_arl[:20]}...", flush=True)
                arl_manager.save_arl_to_env(new_arl)
                # Reload and test new ARL
                DEEZER_ARL = new_arl
                login_success = dz.login_via_arl(DEEZER_ARL)
                if login_success:
                    print(f"🎵 Deezer login with new ARL: ✓ Success", flush=True)
                else:
                    print(f"❌ Login still failed with new ARL", flush=True)
            else:
                print(f"❌ Failed to retrieve new ARL", flush=True)
        else:
            print(f"⚠️  Auto-refresh not configured (missing DEEZER_EMAIL/PASSWORD)", flush=True)
            print(f"⚠️  Use API endpoint to refresh ARL: POST /{API_KEY}/arl/refresh", flush=True)
    except Exception as e:
        print(f"❌ Auto-refresh error: {e}", flush=True)
        print(f"⚠️  Use API endpoint to refresh ARL: POST /{API_KEY}/arl/refresh", flush=True)

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
register_all_routes(app, API_KEY, dz, DEEZER_API, streaming_session, DEBUG, create_arl_manager_from_env)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
