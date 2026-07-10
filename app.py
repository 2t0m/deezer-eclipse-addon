"""
Deezer Eclipse Addon - Streaming addon for Eclipse Music iOS app
Streams full Deezer tracks (not 30s previews) with live Blowfish decryption
"""

import os
import logging
import tempfile
from flask import Flask
from flask_cors import CORS
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from deezer import Deezer
from deemix.settings import load as loadSettings

# Load environment variables
load_dotenv()

# Configure logging level from environment
APP_LOG_LEVEL = os.environ.get('APP_LOG_LEVEL', 'INFO').upper()
log_level_map = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

# Custom formatter to match Gunicorn style with tags
class GunicornFormatter(logging.Formatter):
    def format(self, record):
        # Extract tag from logger name
        logger_name = record.name.split('.')[-1]
        tag_map = {
            'app': 'App',
            'helpers': 'Deezer',
            'search': 'Search',
            'catalog': 'Catalog',
            'stream': 'Stream',
            'crypto': 'Crypto'
        }
        tag = tag_map.get(logger_name, logger_name.capitalize())
        
        # Format: [YYYY-MM-DD HH:MM:SS +0000] [PID] [LEVEL] [Tag] Message
        timestamp = self.formatTime(record, '%Y-%m-%d %H:%M:%S %z')
        pid = os.getpid()
        return f"[{timestamp}] [{pid}] [{record.levelname}] [{tag}] {record.getMessage()}"

# Configure root logger with custom formatter
handler = logging.StreamHandler()
handler.setFormatter(GunicornFormatter())
logging.basicConfig(
    level=log_level_map.get(APP_LOG_LEVEL, logging.INFO),
    handlers=[handler]
)
logger = logging.getLogger(__name__)

# Configuration
DEEZER_API = 'https://api.deezer.com'
API_KEY = os.getenv('API_KEY', '')

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Initialize Deezer client
dz = Deezer()
login_success = False

# Load ARL from environment variable
DEEZER_ARL = os.getenv('DEEZER_ARL', '').strip()

if not DEEZER_ARL:
    logger.error("DEEZER_ARL environment variable not set")
    logger.error("Please set DEEZER_ARL in docker-compose.yml or .env file")
    logger.error("To get your ARL: Open https://www.deezer.com, login, press F12, Application tab, Cookies, copy 'arl' value")
else:
    # Try to login with ARL
    login_success = dz.login_via_arl(DEEZER_ARL)
    if login_success:
        logger.info(f"Deezer login successful with ARL: {DEEZER_ARL[:8]}...")
    else:
        logger.error("Deezer login failed - ARL may be invalid or expired")
        logger.error("To get a new ARL: Open https://www.deezer.com, login, press F12, Application tab, Cookies, copy 'arl' value")

# HTTP session for streaming (reuses connections, avoids SSL handshakes)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

streaming_session = requests.Session()

# Configure connection pool for better performance
adapter = HTTPAdapter(
    pool_connections=10,  # Number of connection pools
    pool_maxsize=20,      # Max connections per pool
    max_retries=Retry(total=3, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
)
streaming_session.mount('http://', adapter)
streaming_session.mount('https://', adapter)

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

logger.info("Configuration loaded successfully")
logger.info(f"App log level: {APP_LOG_LEVEL}")
logger.info(f"Gunicorn log level: {os.environ.get('GUNICORN_LOG_LEVEL', 'WARNING').upper()}")
logger.debug(f"Download location: {settings['downloadLocation']}")

# Register all routes
from routes import register_all_routes
register_all_routes(app, API_KEY, dz, DEEZER_API, streaming_session)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
