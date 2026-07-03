"""
Search routes for Eclipse Music addon
"""

from flask import request, jsonify
import requests
from helpers import validate_token, is_track_streamable, log_debug, log_info


def register_routes(app, api_key, dz, deezer_api):
    """Register search routes"""
    
    @app.route('/<token>/search')
    def search_content(token):
        """Search for tracks, albums and artists on Deezer (returns all types)"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        # Log query parameters (DEBUG only)
        log_debug(f"🔎 Search request: {dict(request.args)}")
        
        query = request.args.get('q', '')
        
        if not query:
            return jsonify({'error': 'Query parameter required'}), 400
        
        try:
            log_debug(f"🔍 Searching: \"{query}\" (all types)")
            
            # Build base URL for streamURL
            base_url = f"https://{request.host}"
            user_agent = request.headers.get('User-Agent', 'Unknown')[:30]
            
            # Initialize result arrays
            streamable_tracks = []
            albums = []
            artists = []
            
            # SEARCH TRACKS
            try:
                search_response = requests.get(f'{deezer_api}/search/track', params={'q': query, 'limit': 25}, timeout=5)
                if search_response.status_code == 200:
                    results = search_response.json().get('data', [])
                    for track in results:
                        track_id = track.get('id')
                        if track_id:
                            streamable, title = is_track_streamable(dz, track_id)
                            if streamable:
                                album_data = track.get('album', {})
                                track_obj = {
                                    'id': str(track_id),
                                    'title': track.get('title', ''),
                                    'artist': track.get('artist', {}).get('name', ''),
                                    'duration': track.get('duration', 0),
                                    'format': 'mp3',
                                    'album': album_data.get('title', ''),
                                    'artworkURL': album_data.get('cover_big', album_data.get('cover_medium', '')),
                                    'isrc': track.get('isrc', ''),
                                    'streamURL': f"{base_url}/{token}/proxy/stream/{track_id}"
                                }
                                streamable_tracks.append(track_obj)
                                if len(streamable_tracks) >= 20:
                                    break
            except Exception as e:
                log_debug(f"⚠ Track search error: {e}")
            
            # SEARCH ALBUMS
            try:
                search_response = requests.get(f'{deezer_api}/search/album', params={'q': query, 'limit': 25}, timeout=5)
                if search_response.status_code == 200:
                    results = search_response.json().get('data', [])
                    for album in results:
                        release_date = album.get('release_date', '')
                        year = int(release_date.split('-')[0]) if release_date and release_date.split('-')[0] else 0
                        album_obj = {
                            'id': str(album.get('id', '')),
                            'title': album.get('title', ''),
                            'artist': album.get('artist', {}).get('name', ''),
                            'artworkURL': album.get('cover_big', album.get('cover_medium', album.get('cover_small', ''))),
                            'trackCount': album.get('nb_tracks', 0),
                            'year': year
                        }
                        albums.append(album_obj)
            except Exception as e:
                log_debug(f"⚠ Album search error: {e}")
            
            # SEARCH ARTISTS
            try:
                search_response = requests.get(f'{deezer_api}/search/artist', params={'q': query, 'limit': 25}, timeout=5)
                if search_response.status_code == 200:
                    results = search_response.json().get('data', [])
                    for artist in results:
                        artist_obj = {
                            'id': str(artist.get('id', '')),
                            'name': artist.get('name', ''),
                            'artworkURL': artist.get('picture_big', artist.get('picture_medium', artist.get('picture_small', '')))
                        }
                        artists.append(artist_obj)
            except Exception as e:
                log_debug(f"⚠ Artist search error: {e}")
            
            # Log results
            log_info(f"[search] [{user_agent}] \"{query[:40]}...\": {len(streamable_tracks)} tracks, {len(albums)} albums, {len(artists)} artists")
            
            # Return combined results
            return jsonify({
                'tracks': streamable_tracks,
                'albums': albums,
                'artists': artists
            })
            
        except Exception as e:
            log_info(f"[search] [{user_agent}] ⚠ Error: {e}")
            return jsonify({'error': str(e)}), 500
