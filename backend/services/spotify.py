import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from typing import List, Dict, Optional
import sys
import os
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class SpotifyService:
    def __init__(self):
        if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
            raise ValueError("Spotify credentials not configured. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET")
        self._init_client()

    def _init_client(self):
        """Initialize or reinitialize the Spotify client (used on startup and after stale connections)."""
        client_credentials_manager = SpotifyClientCredentials(
            client_id=config.SPOTIFY_CLIENT_ID,
            client_secret=config.SPOTIFY_CLIENT_SECRET,
            requests_timeout=15,
        )
        self.client = spotipy.Spotify(
            client_credentials_manager=client_credentials_manager,
            requests_timeout=15,
            retries=3,
        )

    def _call(self, func, *args, **kwargs):
        """Call a Spotify API function, reinitializing the client on connection/timeout errors."""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            if not any(k in msg for k in ('timeout', 'timed out', 'connection', 'remotedisconnected', 'broken pipe')):
                raise
            print(f"Spotify connection error, reinitializing client: {e}")
            self._init_client()
            for attempt in range(3):
                try:
                    return func(*args, **kwargs)
                except Exception as retry_e:
                    retry_msg = str(retry_e).lower()
                    if attempt < 2 and any(k in retry_msg for k in ('timeout', 'timed out', 'connection')):
                        print(f"Retry {attempt + 1} failed, waiting before next attempt: {retry_e}")
                        time.sleep(2 ** attempt)
                        continue
                    raise

    def search_tracks(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for tracks on Spotify"""
        try:
            results = self._call(self.client.search, q=query, type='track', limit=limit, market='MX')
            tracks = []
            
            for item in results['tracks']['items']:
                track = {
                    'id': item['id'],
                    'name': item['name'],
                    'artists': [artist['name'] for artist in item['artists']],
                    'artist': ', '.join([artist['name'] for artist in item['artists']]),
                    'album': item['album']['name'],
                    'album_id': item['album']['id'],
                    'duration_ms': item['duration_ms'],
                    'external_url': item['external_urls']['spotify'],
                    'preview_url': item.get('preview_url'),
                    # Get the largest image (first in array, sorted by size descending)
                    'album_art': item['album']['images'][0]['url'] if item['album']['images'] else None,
                    'release_date': item['album'].get('release_date', '')
                }
                tracks.append(track)
            
            return tracks
        except Exception as e:
            print(f"Spotify search error: {e}")
            raise
    
    def get_track_details(self, track_id: str) -> Optional[Dict]:
        """Get detailed information about a specific track"""
        try:
            track = self._call(self.client.track, track_id)
            return {
                'id': track['id'],
                'name': track['name'],
                'artists': [artist['name'] for artist in track['artists']],
                'artist': ', '.join([artist['name'] for artist in track['artists']]),
                'album_artists': [album_artist['name'] for album_artist in track['album']['artists']],
                'album_artist': ', '.join([album_artist['name'] for album_artist in track['album']['artists']]),
                'album': track['album']['name'],
                'album_id': track['album']['id'],
                'duration_ms': track['duration_ms'],
                'external_url': track['external_urls']['spotify'],
                'preview_url': track.get('preview_url'),
                'track_number': track.get('track_number', 1),
                # Get the largest image (first in array, sorted by size descending)
                'album_art': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'release_date': track['album'].get('release_date', '')
            }
        except Exception as e:
            print(f"Error fetching track details: {e}")
            return None
    
    def search_albums(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for albums on Spotify"""
        try:
            results = self._call(self.client.search, q=query, type='album', limit=limit, market='MX')
            albums = []
            
            for item in results['albums']['items']:
                album = {
                    'id': item['id'],
                    'name': item['name'],
                    'artist': ', '.join([artist['name'] for artist in item['artists']]),
                    'artists': [artist['name'] for artist in item['artists']],
                    'release_date': item.get('release_date', ''),
                    'total_tracks': item.get('total_tracks', 0),
                    'album_art': item['images'][0]['url'] if item['images'] else None,
                    'external_url': item['external_urls']['spotify']
                }
                albums.append(album)
            
            return albums
        except Exception as e:
            print(f"Spotify album search error: {e}")
            raise
    
    def get_album_details(self, album_id: str) -> Optional[Dict]:
        """Get detailed information about an album including all tracks"""
        try:
            album = self._call(self.client.album, album_id)
            
            # Get all tracks from the album (handle pagination for albums with >50 tracks)
            tracks = []
            
            # Process first page of tracks
            for item in album['tracks']['items']:
                track = {
                    'id': item['id'],
                    'name': item['name'],
                    'artists': [artist['name'] for artist in item['artists']],
                    'artist': ', '.join([artist['name'] for artist in item['artists']]),
                    'album': album['name'],
                    'album_id': album['id'],
                    'duration_ms': item['duration_ms'],
                    'track_number': item['track_number'],
                    'external_url': item['external_urls']['spotify'],
                    'preview_url': item.get('preview_url'),
                    'album_art': album['images'][0]['url'] if album['images'] else None,
                    'release_date': album.get('release_date', '')
                }
                tracks.append(track)
            
            # Handle pagination - Spotify API returns max 50 tracks per page
            # Continue fetching tracks until we have all of them
            offset = len(tracks)  # Start from where we left off
            
            # Fetch additional pages if there are more tracks (check if 'next' exists in first page)
            if album['tracks'].get('next'):
                while True:
                    # Fetch next page of tracks using album_tracks method with offset
                    next_page = self.client.album_tracks(album_id, limit=50, offset=offset)
                    
                    if not next_page['items']:
                        break
                    
                    for item in next_page['items']:
                        track = {
                            'id': item['id'],
                            'name': item['name'],
                            'artists': [artist['name'] for artist in item['artists']],
                            'artist': ', '.join([artist['name'] for artist in item['artists']]),
                            'album': album['name'],
                            'album_id': album['id'],
                            'duration_ms': item['duration_ms'],
                            'track_number': item['track_number'],
                            'external_url': item['external_urls']['spotify'],
                            'preview_url': item.get('preview_url'),
                            'album_art': album['images'][0]['url'] if album['images'] else None,
                            'release_date': album.get('release_date', '')
                        }
                        tracks.append(track)
                    
                    # Check if there are more tracks to fetch
                    if not next_page.get('next'):
                        break
                    
                    offset += 50
                    
                    # Safety check to prevent infinite loops (max 1000 tracks should be enough)
                    if offset >= 1000:
                        print(f"Warning: Stopped pagination at 1000 tracks for album {album_id}")
                        break
            
            return {
                'id': album['id'],
                'name': album['name'],
                'artist': ', '.join([artist['name'] for artist in album['artists']]),
                'artists': [artist['name'] for artist in album['artists']],
                'release_date': album.get('release_date', ''),
                'total_tracks': album.get('total_tracks', 0),
                'album_art': album['images'][0]['url'] if album['images'] else None,
                'external_url': album['external_urls']['spotify'],
                'tracks': tracks
            }
        except Exception as e:
            print(f"Error fetching album details: {e}")
            return None

