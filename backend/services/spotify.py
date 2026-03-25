import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from typing import List, Dict, Optional
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class SpotifyService:
    def __init__(self):
        if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
            raise ValueError(
                "Spotify credentials not configured. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET"
            )
        client_credentials_manager = SpotifyClientCredentials(
            client_id=config.SPOTIFY_CLIENT_ID,
            client_secret=config.SPOTIFY_CLIENT_SECRET,
        )
        self.client = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

    def search_tracks(self, query: str, limit: int = 20) -> List[Dict]:
        try:
            results = self.client.search(q=query, type="track", limit=limit)
            tracks = []
            for item in results["tracks"]["items"]:
                tracks.append({
                    "id": item["id"],
                    "name": item["name"],
                    "artists": [artist["name"] for artist in item["artists"]],
                    "artist": ", ".join([artist["name"] for artist in item["artists"]]),
                    "album": item["album"]["name"],
                    "album_id": item["album"]["id"],
                    "duration_ms": item["duration_ms"],
                    "external_url": item["external_urls"]["spotify"],
                    "preview_url": item.get("preview_url"),
                    "album_art": item["album"]["images"][0]["url"] if item["album"]["images"] else None,
                    "release_date": item["album"].get("release_date", ""),
                })
            return tracks
        except Exception as e:
            print(f"Spotify search error: {e}")
            raise

    def get_track_details(self, track_id: str) -> Optional[Dict]:
        try:
            track = self.client.track(track_id)
            return {
                "id": track["id"],
                "name": track["name"],
                "artists": [artist["name"] for artist in track["artists"]],
                "artist": ", ".join([artist["name"] for artist in track["artists"]]),
                "album_artists": [album_artist["name"] for album_artist in track["album"]["artists"]],
                "album_artist": ", ".join([album_artist["name"] for album_artist in track["album"]["artists"]]),
                "album": track["album"]["name"],
                "album_id": track["album"]["id"],
                "duration_ms": track["duration_ms"],
                "external_url": track["external_urls"]["spotify"],
                "preview_url": track.get("preview_url"),
                "track_number": track.get("track_number", 1),
                "album_art": track["album"]["images"][0]["url"] if track["album"]["images"] else None,
                "release_date": track["album"].get("release_date", ""),
            }
        except Exception as e:
            print(f"Error fetching track details: {e}")
            return None

    def search_albums(self, query: str, limit: int = 20) -> List[Dict]:
        try:
            results = self.client.search(q=query, type="album", limit=limit)
            albums = []
            for item in results["albums"]["items"]:
                albums.append({
                    "id": item["id"],
                    "name": item["name"],
                    "artist": ", ".join([artist["name"] for artist in item["artists"]]),
                    "artists": [artist["name"] for artist in item["artists"]],
                    "release_date": item.get("release_date", ""),
                    "total_tracks": item.get("total_tracks", 0),
                    "album_art": item["images"][0]["url"] if item["images"] else None,
                    "external_url": item["external_urls"]["spotify"],
                })
            return albums
        except Exception as e:
            print(f"Spotify album search error: {e}")
            raise

    def get_album_details(self, album_id: str) -> Optional[Dict]:
        try:
            album = self.client.album(album_id)
            tracks = []
            for item in album["tracks"]["items"]:
                tracks.append({
                    "id": item["id"],
                    "name": item["name"],
                    "artists": [artist["name"] for artist in item["artists"]],
                    "artist": ", ".join([artist["name"] for artist in item["artists"]]),
                    "album": album["name"],
                    "album_id": album["id"],
                    "duration_ms": item["duration_ms"],
                    "track_number": item["track_number"],
                    "external_url": item["external_urls"]["spotify"],
                    "preview_url": item.get("preview_url"),
                    "album_art": album["images"][0]["url"] if album["images"] else None,
                    "release_date": album.get("release_date", ""),
                })
            offset = len(tracks)
            if album["tracks"].get("next"):
                while True:
                    next_page = self.client.album_tracks(album_id, limit=50, offset=offset)
                    if not next_page["items"]:
                        break
                    for item in next_page["items"]:
                        tracks.append({
                            "id": item["id"],
                            "name": item["name"],
                            "artists": [artist["name"] for artist in item["artists"]],
                            "artist": ", ".join([artist["name"] for artist in item["artists"]]),
                            "album": album["name"],
                            "album_id": album["id"],
                            "duration_ms": item["duration_ms"],
                            "track_number": item["track_number"],
                            "external_url": item["external_urls"]["spotify"],
                            "preview_url": item.get("preview_url"),
                            "album_art": album["images"][0]["url"] if album["images"] else None,
                            "release_date": album.get("release_date", ""),
                        })
                    if not next_page.get("next"):
                        break
                    offset += 50
                    if offset >= 1000:
                        print(f"Warning: Stopped pagination at 1000 tracks for album {album_id}")
                        break

            return {
                "id": album["id"],
                "name": album["name"],
                "artist": ", ".join([artist["name"] for artist in album["artists"]]),
                "artists": [artist["name"] for artist in album["artists"]],
                "release_date": album.get("release_date", ""),
                "total_tracks": album.get("total_tracks", 0),
                "album_art": album["images"][0]["url"] if album["images"] else None,
                "external_url": album["external_urls"]["spotify"],
                "tracks": tracks,
            }
        except Exception as e:
            print(f"Error fetching album details: {e}")
            return None
