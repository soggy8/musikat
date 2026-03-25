import os
import shutil
import requests
from typing import Dict, Optional
from pathlib import Path
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class NavidromeService:
    def __init__(self):
        self.music_path = config.NAVIDROME_MUSIC_PATH
        self.api_url = config.NAVIDROME_API_URL
        self.username = config.NAVIDROME_USERNAME
        self.password = config.NAVIDROME_PASSWORD
    
    def get_target_path(self, track_info: Dict, file_extension: str) -> Path:
        """Get the target path for a track in Navidrome music directory"""

        # Ensure artist names are joined with semicolons
        if 'artist' in track_info:
            track_info['artist'] = track_info['artist'].replace(',', ';')
            # Extract only the first artist
            artist_name = track_info['artist'].split(';')[0].strip()
        else:
            artist_name = 'Unknown Artist'

        if 'album_artist' in track_info:
            track_info['album_artist'] = track_info['album_artist'].replace(',', ';')
            # Extract only the first artist
            artist_name = track_info['album_artist'].split(';')[0].strip()

        # Create artist directory structure
        artist_name = self._sanitize_path(artist_name)
        album_name = self._sanitize_path(track_info.get('album', 'Unknown Album'))
        
        # Create directory: /music/Artist/Album/
        target_dir = Path(self.music_path) / artist_name / album_name
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Build filename
        filename = self._sanitize_filename(f"{track_info['name']}.{file_extension}")
        target_path = target_dir / filename
        
        # If file exists, add number suffix
        if target_path.exists():
            base_name = target_path.stem
            counter = 1
            while target_path.exists():
                target_path = target_dir / f"{base_name} ({counter}).{file_extension}"
                counter += 1
        
        return target_path
    
    def finalize_track(self, file_path: str) -> Dict:
        """Finalize track by triggering Navidrome scan"""
        try:
            # Trigger Navidrome scan to pick up the new file
            self._trigger_scan()
            
            return {
                'success': True,
                'target_path': file_path,
                'message': 'Track successfully added to Navidrome'
            }
        
        except Exception as e:
            print(f"Navidrome finalization error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def upload_to_navidrome(self, file_path: str, track_info: Dict) -> Dict:
        """Copy file to Navidrome music directory (legacy method, kept for compatibility)"""
        try:
            target_path = self.get_target_path(track_info, Path(file_path).suffix[1:])
            shutil.copy2(file_path, target_path)
            return self.finalize_track(str(target_path))
        except Exception as e:
            print(f"Navidrome upload error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _trigger_scan(self) -> bool:
        """Trigger Navidrome library scan via Subsonic API"""
        if not self.api_url or not self.username or not self.password:
            print("Navidrome API credentials not configured, skipping scan trigger")
            return False
        
        try:
            # Subsonic API endpoint for starting scan
            # Note: This requires admin credentials
            import requests.auth
            
            auth = requests.auth.HTTPBasicAuth(self.username, self.password)
            url = f"{self.api_url}/rest/startScan.view"
            params = {
                'u': self.username,
                'p': self.password,
                'v': '1.16.1',
                'c': 'musikat',
                'f': 'json'
            }
            
            response = requests.get(url, params=params, auth=auth, timeout=10)
            return response.status_code == 200
        
        except Exception as e:
            print(f"Error triggering Navidrome scan: {e}")
            return False
    
    def _sanitize_path(self, path: str) -> str:
        """Remove invalid characters from path"""
        import re
        # Remove invalid characters
        path = re.sub(r'[<>:"/\\|?*]', '', path)
        # Replace multiple spaces with single space
        path = re.sub(r'\s+', ' ', path)
        # Trim
        return path.strip()
    
    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        import re
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Replace multiple spaces with single space
        filename = re.sub(r'\s+', ' ', filename)
        # Trim
        return filename.strip()

