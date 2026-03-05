import yt_dlp
from ytmusicapi import YTMusic
import os
import re
import math
from difflib import SequenceMatcher
from typing import Optional, Dict, List, Any, Tuple
from pathlib import Path
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# Confidence threshold - below this, show candidates to user
CONFIDENCE_THRESHOLD = 0.65

# How strongly to trust YTMusic ordering (bigger = trust rank deeper)
# (tuned to match the debug script's improved model)
DEFAULT_RANK_STRENGTH = float(os.getenv("YTMUSIC_RANK_STRENGTH", "6.0"))

class YouTubeService:
    def __init__(self):
        self.output_format = config.OUTPUT_FORMAT
        self.audio_quality = config.AUDIO_QUALITY
        self.cookies_path = config.YOUTUBE_COOKIES_PATH
        try:
            self.ytmusic = YTMusic()
        except Exception as e:
            print(f"Failed to initialize YTMusic: {e}")
            self.ytmusic = None
    
    def _add_cookies_to_opts(self, ydl_opts: Dict) -> Dict:
        """Add cookies to yt-dlp options if configured."""
        if self.cookies_path and os.path.exists(self.cookies_path):
            ydl_opts['cookiefile'] = self.cookies_path
            print(f"Using YouTube cookies from: {self.cookies_path}")
        elif self.cookies_path:
            print(f"Warning: Cookie file specified but not found: {self.cookies_path}")
        return ydl_opts
    
    def calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity between two strings using SequenceMatcher."""
        str1 = (str1 or "").lower().strip()
        str2 = (str2 or "").lower().strip()
        return SequenceMatcher(None, str1, str2).ratio()

    def normalize_text(self, s: str) -> str:
        """Normalize text for cross-source matching (best-effort, multilingual-safe)."""
        s = (s or "").lower()

        # unify separators
        s = s.replace("–", " ").replace("—", " ").replace("-", " ").replace(":", " ")

        # remove common meta tokens
        meta_tokens = [
            "official audio",
            "official video",
            "official music video",
            "lyrics",
            "lyric video",
            "audio",
            "mv",
            "hd",
            "4k",
            "official",
            "music video",
        ]
        for t in meta_tokens:
            s = s.replace(t, " ")

        # remove bracketed meta (best-effort)
        s = re.sub(r"\((official|mv|music video|lyrics|lyric video|audio|hd|4k)[^)]*\)", " ", s)
        s = re.sub(r"\[(official|mv|music video|lyrics|lyric video|audio|hd|4k)[^\]]*\]", " ", s)

        # normalize feat tokens
        s = re.sub(r"\b(feat\.|feat|ft\.|ft)\b", "feat", s)

        # collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def tokens(self, s: str) -> List[str]:
        s = self.normalize_text(s)
        return [p for p in re.split(r"\s+", s) if p]

    def title_score(self, spotify_title: str, yt_title: str) -> float:
        a = self.normalize_text(spotify_title)
        b = self.normalize_text(yt_title)

        sim = self.calculate_similarity(a, b)

        ts = [t for t in self.tokens(a) if len(t) >= 2 and t not in {"feat"}]
        if ts:
            hits = sum(1 for t in ts if t in b)
            contain = hits / len(ts)
            sim = max(sim, 0.55 * sim + 0.45 * contain)

        if a and a in b:
            sim = max(sim, 0.85)

        return max(0.0, min(sim, 1.0))

    def artist_score(self, spotify_artists: List[str], yt_artists_text: str, yt_title: str) -> Tuple[float, int]:
        """Score artist match against ANY Spotify artist. Returns (score, matched_count)."""
        yt_blob = self.normalize_text(yt_artists_text) + " " + self.normalize_text(yt_title)

        per: List[float] = []
        for a in (spotify_artists or []):
            a_norm = self.normalize_text(a)
            sim = self.calculate_similarity(a_norm, yt_blob)
            if a_norm and a_norm in yt_blob:
                sim = max(sim, 0.95)
            per.append(max(0.0, min(sim, 1.0)))

        if not per:
            return 0.0, 0

        best = max(per)
        matched = sum(1 for s in per if s >= 0.75)

        bonus = 0.0
        if matched >= 2:
            bonus = 0.08
        elif matched == 1:
            bonus = 0.02

        return max(0.0, min(best + bonus, 1.0)), matched

    def parse_duration_to_seconds(self, duration_str: str) -> Optional[int]:
        if not duration_str:
            return None
        parts = duration_str.strip().split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except Exception:
            return None
        return None

    def duration_score(self, spotify_duration_ms: Optional[int], yt_duration_seconds: Optional[int], yt_duration_str: str = "") -> float:
        """Score duration similarity. Accepts either parsed seconds or a duration string."""
        if not spotify_duration_ms:
            return 0.5

        yt_sec = yt_duration_seconds
        if yt_sec is None and yt_duration_str:
            yt_sec = self.parse_duration_to_seconds(yt_duration_str)
        if yt_sec is None:
            return 0.5

        sp_sec = max(1.0, spotify_duration_ms / 1000.0)
        delta = abs(sp_sec - float(yt_sec))

        if delta <= 5:
            return 1.0
        if delta <= 15:
            return 0.85
        if delta <= 30:
            return 0.65
        if delta <= 60:
            return 0.35
        return 0.0

    def rank_prior(self, rank: int, strength: float) -> float:
        r = max(1, rank)
        return math.exp(-(r - 1) / max(1e-6, strength))

    def heuristic_adjustment(self, spotify_title: str, yt_title: str) -> float:
        sp = self.normalize_text(spotify_title)
        yt = self.normalize_text(yt_title)

        adj = 0.0

        sp_live = any(k in sp for k in ["live", "现场", "現場"])
        yt_live = any(k in yt for k in ["live", "现场", "現場"])
        if sp_live and yt_live:
            adj += 0.05

        if ("cover" in yt or "翻唱" in yt) and ("cover" not in sp and "翻唱" not in sp):
            adj -= 0.12

        if "remix" in yt and "remix" not in sp:
            adj -= 0.10

        return adj

    def calculate_match_score(
        self,
        youtube_title: str,
        youtube_channel: str,
        track_name: str,
        artist: str,
        track_info: Optional[Dict] = None,
        rank: int = 1,
        source: str = "ytmusic",
        yt_duration_seconds: Optional[int] = None,
        yt_duration_str: str = "",
    ) -> float:
        """Improved multi-signal match score.

        Mirrors the scoring you validated in [`debug_ytmusic_scoring.py`](debug_ytmusic_scoring.py:1).
        """
        spotify_title = track_name
        spotify_artists = []
        spotify_duration_ms: Optional[int] = None

        if track_info:
            spotify_title = track_info.get("name") or track_name
            spotify_artists = track_info.get("artists") or []
            spotify_duration_ms = track_info.get("duration_ms")

        # Fallback if track_info wasn't provided
        if not spotify_artists:
            spotify_artists = [a.strip() for a in (artist or "").split(",") if a.strip()]

        t_s = self.title_score(spotify_title, youtube_title)
        a_s, _matched = self.artist_score(spotify_artists, youtube_channel, youtube_title)
        d_s = self.duration_score(spotify_duration_ms, yt_duration_seconds, yt_duration_str)

        # Trust YTMusic ordering more than a raw YouTube web search.
        rank_strength = DEFAULT_RANK_STRENGTH
        if source != "ytmusic":
            rank_strength = max(3.0, DEFAULT_RANK_STRENGTH * 0.6)
        r_s = self.rank_prior(rank, rank_strength)

        heur = self.heuristic_adjustment(spotify_title, youtube_title)

        # Combine (same weights as debug script)
        final = (0.45 * t_s) + (0.25 * a_s) + (0.20 * d_s) + (0.10 * r_s) + heur
        final = max(0.0, min(final, 1.0))
        return final
    
    def search_candidates(self, track_name: str, artist: str, track_info: Dict = None, num_results: int = 5) -> Dict:
        """Search YouTube and return top candidates with confidence scores."""
        candidates = []
        yt_dlp_blocked = False  # Track if yt-dlp was blocked

        # Try YTMusic first
        if self.ytmusic:
            try:
                search_query = f"{artist} {track_name}"
                if track_info and track_info.get('album'):
                    search_query += f" {track_info.get('album')}"

                results = self.ytmusic.search(search_query, filter="songs", limit=num_results)

                for idx, res in enumerate(results, start=1):
                    video_id = res.get('videoId')
                    if not video_id:
                        continue

                    title = res.get('title', '')
                    artists_list = res.get('artists', [])
                    channel = ", ".join([a.get('name', '') for a in artists_list]) if artists_list else ''

                    duration_str = res.get('duration', '0:00')
                    duration = 0
                    try:
                        parts = duration_str.split(':')
                        if len(parts) == 2:
                            duration = int(parts[0]) * 60 + int(parts[1])
                        elif len(parts) == 3:
                            duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    except Exception:
                        duration = 0

                    thumbnails = res.get('thumbnails', [])
                    thumbnail = thumbnails[-1].get('url', '') if thumbnails else ''

                    score = self.calculate_match_score(
                        title,
                        channel,
                        track_name,
                        artist,
                        track_info=track_info,
                        rank=idx,
                        source='ytmusic',
                        yt_duration_seconds=duration,
                        yt_duration_str=duration_str,
                    )

                    candidates.append({
                        'video_id': video_id,
                        'title': title,
                        'channel': channel,
                        'duration': duration,
                        'thumbnail': thumbnail,
                        'score': round(score, 3),
                        'url': f"https://music.youtube.com/watch?v={video_id}",
                        'source': 'ytmusic'
                    })
            except Exception as e:
                print(f"YTMusic search failed: {e}")

        # Fallback to yt-dlp if no candidates found or YTMusic failed
        if not candidates:
            if track_info and track_info.get('album'):
                query = f"{artist} {track_name} {track_info.get('album')} official"
            else:
                query = f"{artist} {track_name} official audio"

            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'default_search': f'ytsearch{num_results}',
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
            ydl_opts = self._add_cookies_to_opts(ydl_opts)

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    search_query = f"ytsearch{num_results}:{query}"
                    info = ydl.extract_info(search_query, download=False)

                    if 'entries' in info and info['entries']:
                        for idx, entry in enumerate(info['entries'], start=1):
                            if not entry:
                                continue

                            title = entry.get('title', '')
                            channel = entry.get('channel', entry.get('uploader', ''))
                            video_id = entry.get('id', '')
                            duration = entry.get('duration', 0)
                            thumbnail = entry.get('thumbnail', '')

                            score = self.calculate_match_score(
                                title,
                                channel,
                                track_name,
                                artist,
                                track_info=track_info,
                                rank=idx,
                                source='yt-dlp',
                                yt_duration_seconds=duration if isinstance(duration, int) else None,
                                yt_duration_str="",
                            )

                            candidates.append({
                                'video_id': video_id,
                                'title': title,
                                'channel': channel,
                                'duration': duration,
                                'thumbnail': thumbnail,
                                'score': round(score, 3),
                                'url': f"https://www.youtube.com/watch?v={video_id}",
                                'source': 'yt-dlp'
                            })
            except Exception as e:
                error_msg = str(e)
                # Log the error but don't fail completely - we might have YTMusic candidates
                if '403' in error_msg or 'Forbidden' in error_msg:
                    print(f"yt-dlp search blocked by YouTube (403). Using YTMusic results only: {e}")
                    yt_dlp_blocked = True
                else:
                    print(f"yt-dlp search failed: {e}")
                # Continue with whatever candidates we have (from YTMusic if available)

        # Sort by score descending
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        if not candidates:
            return {
                'success': False,
                'error': "No results found on YouTube or YouTube Music. YouTube may be blocking requests (403). Try using YouTube cookies (see documentation).",
                'candidates': [],
                'needs_confirmation': False
            }

        best_score = candidates[0]['score']
        # Only show confirmation if confidence is really low
        # Disable aggressive confirmation for now - let it work normally
        needs_confirmation = best_score < CONFIDENCE_THRESHOLD
        
        result = {
            'success': True,
            'candidates': candidates[:3],
            'best_score': best_score,
            'needs_confirmation': needs_confirmation,
            'threshold': CONFIDENCE_THRESHOLD
        }
        # Add warning if yt-dlp was blocked
        if yt_dlp_blocked:
            result['warning'] = 'YouTube blocked some requests (403). Consider configuring YouTube cookies for better reliability.'
        return result
    
    def download_by_video_id(self, video_id: str, output_path: str, output_format: str = None, audio_quality: str = None) -> Dict:
        """Download a specific YouTube video by ID"""
        output_format = output_format or self.output_format
        audio_quality = audio_quality or self.audio_quality
        
        output_path = os.path.abspath(output_path)
        base_path = output_path.replace(f'.{output_format}', '')

        # If the user wants m4a and YouTube provides it as itag 140 (m4a/aac),
        # keep the original container by skipping FFmpegExtractAudio.
        wants_m4a_passthrough = (self.output_format or '').lower() == 'm4a'

        ydl_opts = {
            # Avoid HLS (m3u8) formats that get blocked - prefer direct audio formats
            # Format priority: m4a direct > opus/webm direct > bestaudio (non-HLS) > fallback
            'format': 'bestaudio[ext=m4a][protocol!=m3u8]/bestaudio[ext=webm][protocol!=m3u8]/bestaudio[ext=opus][protocol!=m3u8]/bestaudio[protocol!=m3u8]/best[ext=m4a][protocol!=m3u8]/best[ext=webm][protocol!=m3u8]/best[height<=720][protocol!=m3u8]/best',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            # Try different YouTube clients as fallback (helps with 403 errors)
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web', 'ios'],
                }
            },
            'retries': 10,
            'fragment_retries': 10,
            'file_access_retries': 3,
            'outtmpl': base_path,
            'fixup': 'never',
            'quiet': False,
            'no_warnings': False,
            'noplaylist': True,
        }

        # Always add the FFmpegExtractAudio postprocessor when output is m4a
        # This ensures we get a proper .m4a file even if source was Opus/webm
        if wants_m4a_passthrough:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
                # 'preferredquality': '256',
                'nopostoverwrites': False,
            }]
            ydl_opts['postprocessor_args'] = {
                'ffmpeg': [
                    # '-af', 'aresample=44100',
                    '-ac', '2',
                    '-c:a', 'copy',
                    '-q:a', '0',
                ]
            }
        else:
            # For other formats (mp3, flac, etc.), use original logic
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': self.output_format,
                'preferredquality': self.audio_quality,
                'nopostoverwrites': False,
            }]
            ydl_opts['postprocessor_args'] = {
                'ffmpeg': [
                    '-af', 'aresample=44100',
                    '-ac', '2',
                ]
            }
        
        ydl_opts = self._add_cookies_to_opts(ydl_opts)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                url = f"https://www.youtube.com/watch?v={video_id}"
                info = ydl.extract_info(url, download=True)

                # If m4a output requested, and the selected format is itag 140,
                # the downloaded file will already be .m4a.
                # Find the downloaded file
                expected_path = f"{base_path}.m4a" if wants_m4a_passthrough else f"{base_path}.{output_format}"
                if os.path.exists(expected_path):
                    actual_path = expected_path
                else:
                    # Check other extensions
                    actual_path = None
                    for ext in ['m4a', 'webm', 'opus', output_format]:
                        test_path = f"{base_path}.{ext}"
                        if os.path.exists(test_path):
                            actual_path = test_path
                            break

                    if not actual_path:
                        raise FileNotFoundError(f"Downloaded file not found. Expected: {expected_path}")

                return {
                    'success': True,
                    'file_path': actual_path,
                    'title': info.get('title', ''),
                    'duration': info.get('duration', 0),
                    'url': info.get('webpage_url', '')
                }

        except Exception as e:
            error_msg = str(e)
            if '403' in error_msg or 'Forbidden' in error_msg:
                error_msg = "YouTube blocked the request (HTTP 403). Try again in a few minutes."
            return {
                'success': False,
                'error': error_msg
            }
    
    def search_and_download(self, track_name: str, artist: str, output_path: str, track_info: Dict = None, video_id: str = None, output_format: str = None, audio_quality: str = None) -> Dict:
        """Search YouTube for a track and download it. If video_id is provided, download that specific video."""
        output_format = output_format or self.output_format
        audio_quality = audio_quality or self.audio_quality
        
        # If a specific video_id is provided, download it directly
        if video_id:
            return self.download_by_video_id(video_id, output_path, output_format, audio_quality)
        
        # Try to find the best candidate using our search logic (YTMusic with yt-dlp fallback)
        # This ensures album downloads and auto-downloads use the best available source
        try:
            search_result = self.search_candidates(track_name, artist, track_info, num_results=3)
            if search_result.get('success') and search_result.get('candidates'):
                best_candidate = search_result['candidates'][0]
                # Auto-select if we have high confidence match
                if best_candidate['score'] >= CONFIDENCE_THRESHOLD:
                    print(f"Auto-selected best candidate for download: '{best_candidate['title']}' (Score: {best_candidate['score']}, Source: {best_candidate.get('source')})")
                    return self.download_by_video_id(best_candidate['video_id'], output_path, output_format, audio_quality)
        except Exception as e:
            print(f"Pre-download search failed: {e}")

        # Fallback to original yt-dlp search and download logic if no high-confidence candidate found
        # Create more specific search query to get better matches
        # Include album name if available for better matching
        if track_info and track_info.get('album'):
            query = f"{artist} {track_name} {track_info.get('album')} official"
        else:
            query = f"{artist} {track_name} official audio"
        
        # Convert to absolute path to avoid filesystem issues
        output_path = os.path.abspath(output_path)
        base_path = output_path.replace(f'.{output_format}', '')
        
        # If the user wants m4a and YouTube provides it as itag 140 (m4a/aac),
        # keep the original container by skipping FFmpegExtractAudio.
        wants_m4a_passthrough = (output_format or '').lower() == 'm4a'

        ydl_opts = {
            # Avoid HLS (m3u8) formats that get blocked - prefer direct audio formats
            'format': 'bestaudio[ext=m4a][protocol!=m3u8]/bestaudio[ext=webm][protocol!=m3u8]/bestaudio[ext=opus][protocol!=m3u8]/bestaudio[protocol!=m3u8]/best[ext=m4a][protocol!=m3u8]/best[ext=webm][protocol!=m3u8]/best[height<=720][protocol!=m3u8]/best',
            # Robust user agent to avoid 403 errors
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            # Try different YouTube clients as fallback (helps with 403 errors)
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web', 'ios'],  # Try multiple clients
                }
            },
            # Retry configuration for network issues and 403 errors
            'retries': 10,
            'fragment_retries': 10,
            'file_access_retries': 3,
            'outtmpl': base_path,
            'fixup': 'never',  # Skip FixupM4a which causes filesystem errors
            'quiet': False,
            'no_warnings': False,
            'default_search': 'ytsearch1',  # Search and get first result
            'noplaylist': True,
            'extract_flat': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
        }

        # Always add the FFmpegExtractAudio postprocessor when output is m4a
        # This ensures we get a proper .m4a file even if source was Opus/webm
        if wants_m4a_passthrough:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
                # 'preferredquality': '256',
                'nopostoverwrites': False,
            }]
            ydl_opts['postprocessor_args'] = {
                'ffmpeg': [
                    # '-af', 'aresample=44100',
                    '-ac', '2',
                    '-c:a', 'copy',
                    '-q:a', '0',
                ]
            }
        else:
            # For other formats (mp3, flac, etc.), use original logic
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': self.output_format,
                'preferredquality': self.audio_quality,
                'nopostoverwrites': False,
            }]
            ydl_opts['postprocessor_args'] = {
                'ffmpeg': [
                    '-af', 'aresample=44100',
                    '-ac', '2',
                ]
            }
        
        ydl_opts = self._add_cookies_to_opts(ydl_opts)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Search and download in one step (faster)
                search_query = f"ytsearch1:{query}"
                info = ydl.extract_info(search_query, download=True)
                
                # Extract actual video info from ytsearch result (it returns entries)
                if 'entries' in info and info['entries']:
                    video_entry = info['entries'][0]
                    if video_entry:
                        # Validate the match after download
                        youtube_title = (video_entry.get('title') or info.get('title') or '').lower()
                        youtube_uploader = (video_entry.get('uploader') or info.get('uploader') or '').lower()
                        
                        track_name_lower = track_name.lower()
                        artist_parts = [a.strip().lower() for a in artist.lower().split(',')]
                        main_artist = artist_parts[0] if artist_parts else ''
                        
                        # Check if title contains key words from track name
                        track_words = [w for w in track_name_lower.split() if len(w) > 2]
                        title_match = track_name_lower in youtube_title or any(word in youtube_title for word in track_words)
                        artist_match = main_artist in youtube_title or main_artist in youtube_uploader
                        
                        # Log for debugging (non-blocking)
                        print(f"YouTube result: '{video_entry.get('title') or info.get('title')}' by '{video_entry.get('uploader') or info.get('uploader')}'")
                        print(f"Looking for: '{track_name}' by '{artist}' - Match: title={title_match}, artist={artist_match}")
                        
                        # Use the video entry info for return value
                        if video_entry.get('title'):
                            info = video_entry
                
                # yt-dlp returns the actual filename in info dict
                # Try to get the downloaded file path (base_path already set above as absolute)
                actual_path = None
                
                # Check for file with expected extension first (base_path is already absolute)
                expected_path = f"{base_path}.m4a" if wants_m4a_passthrough else f"{base_path}.{self.output_format}"
                
                # Use expected path if it exists (most common case)
                if os.path.exists(expected_path):
                    actual_path = expected_path
                else:
                    # Check for other possible extensions (before conversion)
                    for ext in ['m4a', 'webm', 'opus']:
                        test_path = f"{base_path}.{ext}"
                        if os.path.exists(test_path):
                            # File exists but hasn't been converted yet - this shouldn't happen
                            # as FFmpeg should have converted it, but handle it anyway
                            actual_path = test_path
                            break
                        
                        # Check numbered variants (yt-dlp adds these if file exists)
                        if not actual_path:
                            for i in range(10):
                                test_path = f"{base_path}-{i}.{ext}"
                                if os.path.exists(test_path):
                                    actual_path = test_path
                                    break
                            if actual_path:
                                break
                    
                    # Also check numbered variants of the final format
                    if not actual_path:
                        for i in range(10):
                            test_path = f"{base_path}-{i}.{self.output_format}"
                            if os.path.exists(test_path):
                                actual_path = test_path
                                break
                
                if not actual_path:
                    # Last resort: try to get from info dict
                    filename = ydl.prepare_filename(info)
                    if os.path.exists(filename):
                        actual_path = filename
                    elif os.path.exists(filename.replace('.webm', f'.{self.output_format}')):
                        actual_path = filename.replace('.webm', f'.{self.output_format}')
                    elif os.path.exists(filename.replace('.m4a', f'.{self.output_format}')):
                        actual_path = filename.replace('.m4a', f'.{self.output_format}')
                    else:
                        raise FileNotFoundError(f"Downloaded file not found. Expected: {expected_path}")
                
                return {
                    'success': True,
                    'file_path': actual_path,
                    'title': info.get('title', track_name),
                    'duration': info.get('duration', 0),
                    'url': info.get('webpage_url', '')
                }
        
        except Exception as e:
            error_msg = str(e)
            
            # Provide helpful error messages for common issues
            if '403' in error_msg or 'Forbidden' in error_msg:
                error_msg = "YouTube blocked the request (HTTP 403). This can happen due to rate limiting, IP blocking, or YouTube's anti-bot measures. Try again in a few minutes, or ensure yt-dlp is up to date: pip install --upgrade yt-dlp"
            elif 'HTTP Error' in error_msg:
                error_msg = f"Network error: {error_msg}. Check your internet connection and try again."
            elif 'unable to download video data' in error_msg.lower():
                error_msg = f"YouTube download failed: {error_msg}. This may be due to the video being unavailable, region-locked, or YouTube blocking the request. Try a different track or wait a few minutes."
            
            print(f"YouTube download error: {e}")
            return {
                'success': False,
                'error': error_msg
            }
    
    def sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Replace multiple spaces with single space
        filename = re.sub(r'\s+', ' ', filename)
        # Trim
        filename = filename.strip()
        return filename

    def extract_video_info(self, url_or_id: str) -> Dict:
        """Extract YouTube video metadata (no download).

        Accepts a YouTube/YouTube Music URL or a raw video id.
        """
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'skip_download': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web', 'ios'],
                }
            },
        }
        ydl_opts = self._add_cookies_to_opts(ydl_opts)

        # Build a canonical URL if a bare ID was provided
        url = url_or_id
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", (url_or_id or "")):
            url = f"https://www.youtube.com/watch?v={url_or_id}"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            thumbnails = info.get('thumbnails') or []
            thumb_url = ''
            if isinstance(thumbnails, list) and thumbnails:
                # Pick the last (usually highest res)
                thumb_url = (thumbnails[-1] or {}).get('url') or ''
            if not thumb_url:
                thumb_url = info.get('thumbnail') or ''

            return {
                'success': True,
                'video_id': info.get('id') or '',
                'title': info.get('title') or '',
                'uploader': info.get('uploader') or info.get('channel') or '',
                'duration': info.get('duration') or 0,
                'webpage_url': info.get('webpage_url') or url,
                'thumbnail': thumb_url,
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

