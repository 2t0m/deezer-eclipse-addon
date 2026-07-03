"""
Catalog routes for Eclipse Music addon (album/artist details)
"""

from flask import request, jsonify
import requests
from helpers import validate_token, is_track_streamable, log_debug, log_info


def register_routes(app, api_key, dz, deezer_api):
    """Register catalog routes for albums and artists"""
    
    @app.route('/<token>/album/<album_id>')
    def album_details(token, album_id):
        """Get album details with track list"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        try:
            user_agent = request.headers.get('User-Agent', 'Unknown')[:30]
            base_url = f"https://{request.host}"
            
            # Get album details from Deezer API
            album_response = requests.get(f'{deezer_api}/album/{album_id}', timeout=5)
            if album_response.status_code != 200:
                log_info(f"[catalog:album] [{user_agent}] ⚠ Album {album_id} not found")
                return jsonify({'error': 'Album not found'}), 404
            
            album_data = album_response.json()
            
            # Extract album info
            release_date = album_data.get('release_date', '')
            year = int(release_date.split('-')[0]) if release_date and release_date.split('-')[0] else 0
            
            # Build track list
            tracks = []
            track_list = album_data.get('tracks', {}).get('data', [])
            
            for track in track_list:
                track_id = track.get('id')
                if track_id:
                    streamable, title = is_track_streamable(dz, track_id)
                    if streamable:
                        track_obj = {
                            'id': str(track_id),
                            'title': track.get('title', ''),
                            'artist': track.get('artist', {}).get('name', ''),
                            'duration': track.get('duration', 0),
                            'format': 'mp3',
                            'artworkURL': album_data.get('cover_big', album_data.get('cover_medium', '')),
                            'isrc': track.get('isrc', ''),
                            'streamURL': f"{base_url}/{token}/proxy/stream/{track_id}"
                        }
                        tracks.append(track_obj)
            
            # Build response
            response = {
                'id': str(album_id),
                'title': album_data.get('title', ''),
                'artist': album_data.get('artist', {}).get('name', ''),
                'artworkURL': album_data.get('cover_big', album_data.get('cover_medium', '')),
                'year': year,
                'trackCount': len(tracks),
                'tracks': tracks
            }
            
            log_info(f"[catalog:album] [{user_agent}] Album {album_id}: {len(tracks)} tracks")
            return jsonify(response)
            
        except Exception as e:
            user_agent = request.headers.get('User-Agent', 'Unknown')[:30]
            log_info(f"[catalog:album] [{user_agent}] ⚠ Error {album_id}: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/<token>/artist/<artist_id>')
    def artist_details(token, artist_id):
        """Get artist details with top tracks and albums"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        try:
            user_agent = request.headers.get('User-Agent', 'Unknown')[:30]
            base_url = f"https://{request.host}"
            
            # Get artist details from Deezer API
            artist_response = requests.get(f'{deezer_api}/artist/{artist_id}', timeout=5)
            if artist_response.status_code != 200:
                log_info(f"[catalog:artist] [{user_agent}] ⚠ Artist {artist_id} not found")
                return jsonify({'error': 'Artist not found'}), 404
            
            artist_data = artist_response.json()
            
            # Get top tracks
            top_tracks = []
            try:
                top_response = requests.get(f'{deezer_api}/artist/{artist_id}/top?limit=10', timeout=5)
                if top_response.status_code == 200:
                    top_data = top_response.json().get('data', [])
                    for track in top_data:
                        track_id = track.get('id')
                        if track_id:
                            streamable, title = is_track_streamable(dz, track_id)
                            if streamable:
                                track_obj = {
                                    'id': str(track_id),
                                    'title': track.get('title', ''),
                                    'artist': track.get('artist', {}).get('name', ''),
                                    'duration': track.get('duration', 0),
                                    'format': 'mp3',
                                    'artworkURL': track.get('album', {}).get('cover_big', track.get('album', {}).get('cover_medium', '')),
                                    'isrc': track.get('isrc', ''),
                                    'streamURL': f"{base_url}/{token}/proxy/stream/{track_id}"
                                }
                                top_tracks.append(track_obj)
            except Exception as e:
                log_debug(f"⚠ Top tracks error: {e}")
            
            # Get albums
            albums = []
            try:
                albums_response = requests.get(f'{deezer_api}/artist/{artist_id}/albums?limit=25', timeout=5)
                if albums_response.status_code == 200:
                    albums_data = albums_response.json().get('data', [])
                    for album in albums_data:
                        release_date = album.get('release_date', '')
                        year = release_date.split('-')[0] if release_date and release_date.split('-')[0] else ''
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
                log_debug(f"⚠ Albums error: {e}")
            
            # Build response
            artwork_url = (
                artist_data.get('picture_xl') or 
                artist_data.get('picture_big') or 
                artist_data.get('picture_medium') or 
                artist_data.get('picture') or 
                ''
            )
            
            response = {
                'id': str(artist_id),
                'name': artist_data.get('name', ''),
                'artworkURL': artwork_url,
                'topTracks': top_tracks,
                'albums': albums
            }
            
            # Add optional fields if available
            if 'bio' in artist_data:
                response['bio'] = artist_data['bio']
            if 'genres' in artist_data:
                response['genres'] = artist_data['genres']
            
            log_info(f"[catalog:artist] [{user_agent}] Artist {artist_id}: {len(top_tracks)} tracks, {len(albums)} albums")
            return jsonify(response)
            
        except Exception as e:
            user_agent = request.headers.get('User-Agent', 'Unknown')[:30]
            log_info(f"[catalog:artist] [{user_agent}] ⚠ Error {artist_id}: {e}")
            return jsonify({'error': str(e)}), 500
