"""
Search routes for Eclipse Music addon
"""

import logging
from flask import request, jsonify
import requests
from helpers import (
    build_track_search_queries,
    get_request_base_url,
    validate_token,
    is_track_streamable,
)

logger = logging.getLogger(__name__)


def register_routes(app, api_key, dz, deezer_api):
    """Register search routes"""
    
    @app.route('/<token>/music/search')
    @app.route('/<token>/search')
    def search_content(token):
        """Search for tracks, albums and artists on Deezer (returns all types)"""
        if not validate_token(token, api_key):
            return jsonify({'error': 'Unauthorized'}), 401
        
        query = request.args.get('q', '')
        
        if not query:
            return jsonify({'error': 'Query parameter required'}), 400
        
        try:
            # Normalize query for better Deezer API matching
            # Deezer API is strict: "Remaster" != "Remastered"
            normalized_query = query
            normalized_query = normalized_query.replace('Remastered', 'Remaster')
            normalized_query = normalized_query.replace('remastered', 'remaster')
            
            if normalized_query != query:
                logger.debug(f"Query normalized: '{query}' -> '{normalized_query}'")
            
            logger.debug(f"Searching: {normalized_query}")
            
            # Build base URL for streamURL
            base_url = get_request_base_url()
            
            # Initialize result arrays
            streamable_tracks = []
            albums = []
            artists = []
            playlists = []
            
            # SEARCH TRACKS
            try:
                candidates = []
                seen_track_ids = set()
                for track_query in build_track_search_queries(normalized_query):
                    search_response = requests.get(
                        f'{deezer_api}/search/track',
                        params={'q': track_query, 'limit': 25},
                        timeout=5
                    )
                    if search_response.status_code != 200:
                        continue
                    for track in search_response.json().get('data', []):
                        track_id = track.get('id')
                        if track_id and track_id not in seen_track_ids:
                            seen_track_ids.add(track_id)
                            candidates.append(track)

                for track in candidates:
                    track_id = track.get('id')
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
                logger.debug(f"Track search error: {e}")
            
            # SEARCH ALBUMS
            try:
                search_response = requests.get(f'{deezer_api}/search/album', params={'q': normalized_query, 'limit': 25}, timeout=5)
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
                logger.debug(f"Album search error: {e}")
            
            # SEARCH ARTISTS
            try:
                search_response = requests.get(f'{deezer_api}/search/artist', params={'q': normalized_query, 'limit': 25}, timeout=5)
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
                logger.debug(f"Artist search error: {e}")

            # SEARCH PLAYLISTS
            try:
                search_response = requests.get(
                    f'{deezer_api}/search/playlist',
                    params={'q': normalized_query, 'limit': 25},
                    timeout=5
                )
                if search_response.status_code == 200:
                    results = search_response.json().get('data', [])
                    for playlist in results:
                        playlists.append({
                            'id': str(playlist.get('id', '')),
                            'title': playlist.get('title', ''),
                            'description': playlist.get('description', ''),
                            'artworkURL': playlist.get('picture_big', playlist.get('picture_medium', '')),
                            'creator': playlist.get('user', {}).get('name', ''),
                            'trackCount': playlist.get('nb_tracks', 0)
                        })
            except Exception as e:
                logger.debug(f"Playlist search error: {e}")
            
            # Log results
            logger.info(
                f"Search: {query[:40]}: {len(streamable_tracks)} tracks, "
                f"{len(albums)} albums, {len(artists)} artists, {len(playlists)} playlists"
            )
            
            # Return combined results
            return jsonify({
                'tracks': streamable_tracks,
                'albums': albums,
                'artists': artists,
                'playlists': playlists
            })
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return jsonify({'error': str(e)}), 500
