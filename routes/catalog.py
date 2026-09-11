"""
Catalog routes for Eclipse Music addon (album/artist details)
"""

import logging
from flask import request, jsonify
import requests
from helpers import get_request_base_url, validate_token, is_track_streamable

logger = logging.getLogger(__name__)

CATALOG_ENDPOINTS = {
    'charts': ('track', '/chart/0/tracks'),
    'popular-albums': ('album', '/chart/0/albums'),
    'new-releases': ('album', '/chart/0/albums'),
    'featured-playlists': ('playlist', '/chart/0/playlists')
}


def build_playlist_track(track, base_url, token, artwork_url=''):
    """Build an Eclipse track object from Deezer playlist metadata."""
    album = track.get('album', {})
    item = {
        'id': str(track.get('id', '')),
        'title': track.get('title', ''),
        'artist': track.get('artist', {}).get('name', ''),
        'album': album.get('title', ''),
        'duration': track.get('duration', 0),
        'format': 'mp3',
        'artworkURL': album.get('cover_big', album.get('cover_medium', artwork_url)),
        'streamURL': f"{base_url}/{token}/proxy/stream/{track.get('id')}"
    }
    isrc = track.get('isrc')
    if isrc:
        item['isrc'] = isrc
    return item


def build_catalog_item(item, item_type):
    """Map a Deezer chart item to the compact Eclipse catalog contract."""
    if item_type == 'track':
        album = item.get('album', {})
        result = {
            'id': str(item.get('id', '')),
            'type': 'track',
            'title': item.get('title', ''),
            'artist': item.get('artist', {}).get('name', ''),
            'album': album.get('title', ''),
            'durationMs': int(item.get('duration', 0)) * 1000,
            'artworkURL': album.get('cover_big', album.get('cover_medium', '')),
            'explicit': bool(item.get('explicit_lyrics', False))
        }
        if item.get('isrc'):
            result['isrc'] = item['isrc']
        return result

    if item_type == 'album':
        release_date = item.get('release_date', '')
        return {
            'id': str(item.get('id', '')),
            'type': 'album',
            'title': item.get('title', ''),
            'artist': item.get('artist', {}).get('name', ''),
            'artworkURL': item.get('cover_big', item.get('cover_medium', '')),
            'year': release_date.split('-')[0] if release_date else ''
        }

    return {
        'id': str(item.get('id', '')),
        'type': 'playlist',
        'title': item.get('title', ''),
        'artist': item.get('user', {}).get('name', ''),
        'artworkURL': item.get('picture_big', item.get('picture_medium', ''))
    }


def register_routes(app, api_key, dz, deezer_api):
    """Register catalog routes for albums and artists"""

    @app.route('/<token>/catalog/<catalog_id>')
    def catalog_items(token, catalog_id):
        """Return a page from a declared Eclipse catalog."""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401

        catalog = CATALOG_ENDPOINTS.get(catalog_id)
        if not catalog:
            return jsonify({'error': 'Catalog not found'}), 404

        try:
            skip = int(request.args.get('skip', 0))
            if skip < 0 or skip % 100 != 0:
                return jsonify({'error': 'skip must be a non-negative multiple of 100'}), 400
        except ValueError:
            return jsonify({'error': 'Invalid skip'}), 400

        item_type, endpoint = catalog
        try:
            response = requests.get(
                f'{deezer_api}{endpoint}',
                params={'index': skip, 'limit': 100},
                timeout=5
            )
            if response.status_code != 200:
                return jsonify({'items': []})

            items = [
                build_catalog_item(item, item_type)
                for item in response.json().get('data', [])
                if item.get('id')
            ]
            return jsonify({'items': items})
        except requests.RequestException as error:
            logger.warning(f"Catalog {catalog_id} lookup failed: {error}")
            return jsonify({'items': []})
    
    @app.route('/<token>/album/<album_id>')
    def album_details(token, album_id):
        """Get album details with track list"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        try:
            base_url = get_request_base_url()
            
            # Get album details from Deezer API
            album_response = requests.get(f'{deezer_api}/album/{album_id}', timeout=5)
            if album_response.status_code != 200:
                logger.info(f"Album {album_id} not found")
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
            
            logger.info(f"Album {album_id}: {len(tracks)} tracks")
            return jsonify(response)
            
        except Exception as e:
            logger.error(f"Album {album_id} error: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/<token>/artist/<artist_id>')
    def artist_details(token, artist_id):
        """Get artist details with top tracks and albums"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        try:
            base_url = get_request_base_url()
            
            # Get artist details from Deezer API
            artist_response = requests.get(f'{deezer_api}/artist/{artist_id}', timeout=5)
            if artist_response.status_code != 200:
                logger.info(f"Artist {artist_id} not found")
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
                logger.debug(f"Top tracks error: {e}")
            
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
                logger.debug(f"Albums error: {e}")
            
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
            
            logger.info(f"Artist {artist_id}: {len(top_tracks)} tracks, {len(albums)} albums")
            return jsonify(response)
            
        except Exception as e:
            logger.error(f"Artist {artist_id} error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/<token>/playlist/<playlist_id>')
    def playlist_details(token, playlist_id):
        """Get playlist metadata and up to 500 playable Deezer tracks."""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401

        if not playlist_id.isdigit():
            return jsonify({'error': 'Invalid playlist ID'}), 400

        try:
            playlist_response = requests.get(f'{deezer_api}/playlist/{playlist_id}', timeout=5)
            if playlist_response.status_code != 200:
                return jsonify({'error': 'Playlist not found'}), 404

            playlist = playlist_response.json()
            track_data = list(playlist.get('tracks', {}).get('data', []))
            total = min(int(playlist.get('nb_tracks', len(track_data))), 500)

            while len(track_data) < total:
                page_response = requests.get(
                    f'{deezer_api}/playlist/{playlist_id}/tracks',
                    params={'index': len(track_data), 'limit': min(100, total - len(track_data))},
                    timeout=5
                )
                if page_response.status_code != 200:
                    break
                page = page_response.json().get('data', [])
                if not page:
                    break
                track_data.extend(page)

            base_url = get_request_base_url()
            artwork_url = playlist.get('picture_big', playlist.get('picture_medium', ''))
            tracks = [
                build_playlist_track(track, base_url, token, artwork_url)
                for track in track_data[:total]
                if track.get('id') and track.get('readable', True)
            ]
            return jsonify({
                'id': str(playlist_id),
                'title': playlist.get('title', ''),
                'description': playlist.get('description', ''),
                'artworkURL': artwork_url,
                'creator': playlist.get('creator', {}).get('name', ''),
                'trackCount': len(tracks),
                'tracks': tracks
            })
        except (requests.RequestException, TypeError, ValueError) as error:
            logger.error(f"Playlist {playlist_id} error: {error}")
            return jsonify({'error': 'Could not load playlist'}), 502
