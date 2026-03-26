from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from urllib.parse import quote, unquote
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
import os
import re
import sys
import shutil
from pathlib import Path
import time

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from services.deezer import DeezerService
from services.spotify import SpotifyService
from utils.job_store import (
    init_jobs_db,
    reset_stale_inflight_jobs,
    upsert_job,
    get_job,
    get_album_aggregate,
    record_completed_download,
    has_completed_download,
)

ALLOWED_METADATA_PROVIDERS = frozenset({"deezer", "spotify"})


def resolve_metadata_provider(raw: Optional[str]) -> str:
    p = (raw or config.DEFAULT_METADATA_PROVIDER or "deezer").lower().strip()
    if p not in ALLOWED_METADATA_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid metadata provider. Use one of: {', '.join(sorted(ALLOWED_METADATA_PROVIDERS))}",
        )
    return p


def get_metadata_service(provider: str):
    if provider == "deezer":
        return deezer_service
    if provider == "spotify":
        if spotify_service is None:
            raise HTTPException(
                status_code=503,
                detail="Spotify is not configured. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your environment.",
            )
        return spotify_service
    raise HTTPException(status_code=400, detail="Unknown metadata provider")


def get_system_downloads_folder():
    """Get the user's system Downloads folder"""
    home = Path.home()

    # Check common Downloads folder locations
    if os.name == 'nt':  # Windows
        downloads = home / "Downloads"
    else:  # Linux/Mac
        downloads = home / "Downloads"

    # Create if doesn't exist
    downloads.mkdir(parents=True, exist_ok=True)
    return str(downloads)


from services.youtube import YouTubeService
from services.metadata import MetadataService
from services.navidrome import NavidromeService
from utils.file_handler import get_download_path
from utils.navidrome_library_sync import start_navidrome_library_sync_background

app = FastAPI(title="Musikat API", version="1.0.0")

init_jobs_db()
_stale = reset_stale_inflight_jobs()
if _stale:
    print(f"Reset {_stale} stale download job(s) (queued/processing) after server start")

# CORS middleware (still useful for API endpoints)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

deezer_service = DeezerService()
try:
    spotify_service = SpotifyService()
except Exception as e:
    print(f"Spotify not available (optional): {e}")
    spotify_service = None

youtube_service = YouTubeService()
metadata_service = MetadataService()
navidrome_service = NavidromeService()

start_navidrome_library_sync_background(deezer_service, spotify_service)


def physical_track_file_exists(track_info: dict, location: str, output_format: str) -> bool:
    """True if an audio file for this track already exists at the target location."""
    if location == "local":
        root = get_download_path(track_info, config.DOWNLOAD_DIR, output_format)
        if os.path.isfile(root):
            return True
        temp_dir = os.path.join(config.DOWNLOAD_DIR, "temp")
        temp_p = get_download_path(track_info, temp_dir, output_format)
        return os.path.isfile(temp_p)
    if location == "navidrome":
        return navidrome_service.track_file_exists(track_info, output_format)
    return False


def get_duplicate_download_reason(
    track_id: str,
    provider: str,
    location: str,
    output_format: str,
    track_info: Optional[dict] = None,
) -> Optional[str]:
    """None if download is allowed; otherwise a short message for HTTP 409.

    Local browser downloads do not use completed_track_downloads. Navidrome does,
    so we block duplicates there when the DB says the track was already added.
    """
    job = get_job(track_id)
    if job and job.get("status") in ("queued", "processing"):
        return "A download is already in progress for this track."

    if track_info is None:
        svc = deezer_service if provider == "deezer" else spotify_service
        if svc is None:
            return None
        track_info = svc.get_track_details(track_id)
    if not track_info:
        return None

    if location == "navidrome" and has_completed_download(track_id, provider):
        return "This track was already downloaded."

    if physical_track_file_exists(track_info, location, output_format):
        return "This track is already in your library."

    return None


# Request models
class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 20
    provider: Optional[str] = None  # "deezer" | "spotify"


class DownloadRequest(BaseModel):
    track_id: str
    location: Optional[str] = "local"  # 'local' or 'navidrome'
    video_id: Optional[str] = None  # YouTube video ID if user selected a specific candidate
    format: Optional[str] = None  # Audio format (mp3, m4a, opus, ogg, flac)
    quality: Optional[str] = None  # Audio quality/bitrate (e.g., "128", "192", "256", "320")
    provider: Optional[str] = None  # "deezer" | "spotify"


class AlbumDownloadRequest(BaseModel):
    album_id: str
    location: Optional[str] = "local"  # 'local' or 'navidrome'
    format: Optional[str] = None  # Audio format (mp3, m4a, opus, ogg, flac)
    quality: Optional[str] = None  # Audio quality/bitrate (e.g., "128", "192", "256", "320")
    provider: Optional[str] = None  # "deezer" | "spotify"


class ReverseLookupRequest(BaseModel):
    url: str
    provider: Optional[str] = None  # "deezer" | "spotify"


class ReverseDownloadRequest(BaseModel):
    youtube_url: str
    location: Optional[str] = "local"  # 'local' or 'navidrome'
    spotify_track_id: Optional[str] = None  # Catalog track id (Spotify or Deezer depending on provider)
    metadata: Optional[Dict] = None
    provider: Optional[str] = None  # "deezer" | "spotify"


# Response models
class TrackResponse(BaseModel):
    id: str
    name: str
    artist: str
    artists: List[str]
    album: str
    duration_ms: int
    external_url: str
    preview_url: Optional[str]
    album_art: Optional[str]
    release_date: str


class DownloadStatusResponse(BaseModel):
    status: str
    message: str
    file_path: Optional[str] = None


def download_and_process(
    track_id: str,
    location: str = "local",
    video_id: str = None,
    output_format: str = None,
    audio_quality: str = None,
    metadata_provider: str = "deezer",
):
    """Background task to download and process a track"""
    # Use provided format/quality or fall back to config defaults
    output_format = output_format or config.OUTPUT_FORMAT
    audio_quality = audio_quality or config.AUDIO_QUALITY
    
    try:
        svc = deezer_service if metadata_provider == "deezer" else spotify_service
        if svc is None:
            upsert_job(
                track_id,
                status="error",
                message="Spotify is not configured",
                progress=0,
            )
            return

        upsert_job(
            track_id,
            status="processing",
            message="Fetching track info...",
            stage="fetching",
            progress=10,
        )

        track_info = svc.get_track_details(track_id)
        if not track_info:
            upsert_job(track_id,
                       status="error",
                       message="Could not fetch track information",
                       progress=0
                       )
            return

        upsert_job(track_id, status="processing", message="Preparing download location...", stage="preparing",
                   progress=15)

        # Determine download path based on location preference
        if location == "navidrome":
            # Download directly to Navidrome music directory with proper structure (Artist/Album/)
            # First download to temp location, then copy to Navidrome directory
            temp_dir = os.path.join(config.DOWNLOAD_DIR, "temp")
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            download_path = get_download_path(track_info, temp_dir, output_format)
            print(f"Downloading track {track_id} for Navidrome: {download_path}")
        else:
            # For local downloads: download to temp folder, then serve via browser download
            # This allows each user's browser to save to their own Downloads folder
            temp_dir = os.path.join(config.DOWNLOAD_DIR, "temp")
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            download_path = get_download_path(track_info, temp_dir, output_format)
            print(f"Downloading track {track_id} for local browser download: {download_path}")

        upsert_job(track_id,
                   status="processing",
                   message="Searching YouTube and downloading...",
                   stage="downloading",
                   progress=30)

        # Download - pass full track_info for better matching
        # If video_id is provided, download that specific video
        download_result = youtube_service.search_and_download(
            track_info['name'],
            track_info['artist'],
            download_path,
            track_info,  # Pass full track info for validation
            video_id,  # Specific YouTube video if user selected one
            output_format,  # User-selected format
            audio_quality  # User-selected quality
        )

        if not download_result.get("success"):
            upsert_job(
                track_id,
                status="error",
                message=f"Download failed: {download_result.get('error', 'Unknown error')}",
                progress=0,
            )
            return

        upsert_job(track_id,
                   status="processing",
                   message="Applying metadata...",
                   stage="tagging",
                   progress=85)

        # Apply metadata to downloaded file
        metadata_service.apply_metadata(download_result['file_path'], track_info)

        # Handle completion based on location
        if location == "navidrome":
            # Copy to Navidrome music directory with proper structure (Artist/Album/)
            upsert_job(track_id,
                       status="processing",
                       message="Copying to Navidrome library...",
                       stage="copying",
                       progress=90)

            try:
                # Get target path in Navidrome directory (Artist/Album/filename.mp3)
                target_path = navidrome_service.get_target_path(track_info, config.OUTPUT_FORMAT)

                # Copy file to Navidrome directory
                shutil.copy2(download_result['file_path'], target_path)

                # Clean up temp file
                if os.path.exists(download_result['file_path']):
                    os.remove(download_result['file_path'])

                # Trigger Navidrome scan
                navidrome_result = navidrome_service.finalize_track(str(target_path))

                if navidrome_result.get('success'):
                    upsert_job(track_id,
                               status="completed",
                               message="Track successfully added to Navidrome library",
                               file_path=str(target_path),
                               stage="completed",
                               progress=100
                               )
                    record_completed_download(track_id, metadata_provider)

                else:
                    upsert_job(track_id,
                               status="completed",
                               message=f"Track added to library (scan may need manual trigger): {navidrome_result.get('error', '')}",
                               file_path=str(target_path),
                               stage="completed",
                               progress=100
                               )
                    record_completed_download(track_id, metadata_provider)

            except Exception as e:
                upsert_job(track_id,
                           status="error",
                           message=f"Failed to copy to Navidrome: {str(e)}",
                           progress=0
                           )
        else:
            # For local downloads, provide download URL for browser to handle
            # The file is ready, browser will download it to user's Downloads folder
            filename = os.path.basename(download_result['file_path'])
            # URL encode the filename to handle special characters (use query parameter)
            encoded_filename = quote(filename, safe='')
            download_url = f"api/download/file/{track_id}?filename={encoded_filename}"
            upsert_job(track_id,
                       status="completed",
                       message="Track ready for download",
                       file_path=download_result['file_path'],
                       download_url=download_url,  # URL to trigger browser download
                       stage="completed",
                       progress=100
                       )

    except Exception as e:
        upsert_job(track_id,
                   status="error",
                   message=f"Error: {str(e)}",
                   progress=0
                   )


@app.middleware("http")
async def add_root_path(request: Request, call_next):
    root_path = request.headers.get("X-Forwarded-Prefix", "")
    request.scope["root_path"] = root_path
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the frontend index.html"""
    template_name = "index.html"
    return templates.TemplateResponse(template_name, context={"request": request})


@app.get("/api/metadata/providers")
async def metadata_providers():
    """Available metadata sources and server default."""
    return {
        "default": config.DEFAULT_METADATA_PROVIDER,
        "providers": [
            {"id": "deezer", "label": "Deezer", "configured": True},
            {
                "id": "spotify",
                "label": "Spotify",
                "configured": spotify_service is not None,
            },
        ],
    }


@app.post("/api/search", response_model=List[TrackResponse])
async def search_tracks(request: SearchRequest):
    """Search for tracks using the selected catalog provider."""
    provider = resolve_metadata_provider(request.provider)
    svc = get_metadata_service(provider)
    try:
        return svc.search_tracks(request.query, request.limit or 20)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@app.post("/api/reverse/youtube")
async def reverse_lookup_youtube(request: ReverseLookupRequest):
    """Given a YouTube URL, extract title and search the selected catalog."""
    provider = resolve_metadata_provider(request.provider)
    svc = get_metadata_service(provider)
    try:
        yt_info = youtube_service.extract_video_info(request.url)
        if not yt_info.get('success'):
            raise HTTPException(status_code=400,
                                detail=f"Failed to read YouTube URL: {yt_info.get('error', 'Unknown error')}")

        title = (yt_info.get('title') or '').strip()
        if not title:
            raise HTTPException(status_code=400, detail="YouTube title was empty")

        candidates = svc.search_tracks(title, limit=5)

        return {
            "youtube": yt_info,
            "query": title,
            "spotify_candidates": candidates,
            "provider": provider,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reverse lookup failed: {str(e)}")


@app.post("/api/search/tracks/top")
async def search_tracks_top(request: SearchRequest):
    """Search tracks with a small default limit (pick-lists)."""
    provider = resolve_metadata_provider(request.provider)
    svc = get_metadata_service(provider)
    try:
        limit = request.limit or 5
        limit = max(1, min(int(limit), 10))
        return svc.search_tracks(request.query, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@app.post("/api/search/albums")
async def search_albums(request: SearchRequest):
    """Search for albums."""
    provider = resolve_metadata_provider(request.provider)
    svc = get_metadata_service(provider)
    try:
        return svc.search_albums(request.query, request.limit or 20)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Album search failed: {str(e)}")


@app.get("/api/album/{album_id}")
async def get_album(album_id: str, provider: Optional[str] = Query(None)):
    """Get album details including all tracks"""
    p = resolve_metadata_provider(provider)
    svc = get_metadata_service(p)
    try:
        album = svc.get_album_details(album_id)
        if not album:
            raise HTTPException(status_code=404, detail="Album not found")
        return album
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching album: {str(e)}")


@app.get("/api/track/{track_id}", response_model=TrackResponse)
async def get_track(track_id: str, provider: Optional[str] = Query(None)):
    """Get details for a specific track"""
    p = resolve_metadata_provider(provider)
    svc = get_metadata_service(p)
    try:
        track = svc.get_track_details(track_id)
        if not track:
            raise HTTPException(status_code=404, detail="Track not found")
        return track
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching track: {str(e)}")


@app.post("/api/download")
async def download_track(request: DownloadRequest, background_tasks: BackgroundTasks):
    """Start downloading a track"""
    if request.location not in ["local", "navidrome"]:
        request.location = "local"

    provider = resolve_metadata_provider(request.provider)
    get_metadata_service(provider)

    output_format = request.format or config.OUTPUT_FORMAT
    dup = get_duplicate_download_reason(
        request.track_id, provider, request.location, output_format
    )
    if dup:
        raise HTTPException(status_code=409, detail=dup)

    location_msg = "local downloads folder" if request.location == "local" else "Navidrome server"
    upsert_job(
        request.track_id,
        status="queued",
        message=f"Download queued for {location_msg}",
        progress=0,
        stage="queued",
        payload={"provider": provider, "record_track_id": request.track_id},
    )
    background_tasks.add_task(
        download_and_process,
        request.track_id,
        request.location,
        request.video_id,
        request.format,
        request.quality,
        provider,
    )

    return {
        "status": "queued",
        "message": f"Download started to {location_msg}",
        "track_id": request.track_id,
    }


def reverse_download_and_process(
    job_id: str,
    youtube_url: str,
    location: str,
    track_id: Optional[str],
    metadata: Optional[Dict],
    metadata_provider: str = "deezer",
):
    """Background task: download a specific YouTube URL and tag using catalog or manual metadata."""
    try:
        upsert_job(job_id, status="processing", message="Extracting YouTube info...", stage="fetching", progress=10)

        yt_info = youtube_service.extract_video_info(youtube_url)
        if not yt_info.get('success'):
            upsert_job(job_id, status="error",
                       message=f"Failed to read YouTube URL: {yt_info.get('error', 'Unknown error')}", progress=0)
            return

        video_id = yt_info.get('video_id')
        if not video_id:
            upsert_job(job_id, status="error", message="Could not determine YouTube video id", progress=0)
            return

        track_info: Optional[Dict] = None
        if track_id:
            svc = deezer_service if metadata_provider == "deezer" else spotify_service
            if svc is None:
                upsert_job(job_id, status="error", message="Spotify is not configured", progress=0)
                return
            upsert_job(job_id, status="processing", message="Fetching track info...", stage="fetching",
                       progress=20)
            track_info = svc.get_track_details(track_id)
            if not track_info:
                upsert_job(job_id, status="error", message="Could not fetch track information", progress=0)
                return
        else:
            # Validate manual metadata (name + artist required)
            md = metadata or {}
            name = (md.get('name') or md.get('title') or '').strip()
            artist = (md.get('artist') or '').strip()
            if not name or not artist:
                upsert_job(job_id, status="error", message="Manual metadata requires 'name' (song title) and 'artist'",
                           progress=0)
                return

            # Default album/album_artist to "YouTube" if not provided
            album_artist = (md.get('album_artist') or '').strip() or "YouTube"
            album = (md.get('album') or md.get('album_name') or '').strip() or "YouTube"

            # If user didn't provide album art, use YouTube thumbnail
            album_art = md.get('album_art') or yt_info.get('thumbnail') or None

            track_info = {
                'id': job_id,
                'name': name,
                'artist': artist,
                'artists': [a.strip() for a in re.split(r"[;,]", artist) if a.strip()],
                'album_artist': album_artist,
                'album': album,
                'track_number': int(md.get('track_number') or 1),
                'release_date': (md.get('release_date') or '').strip(),
                'album_art': album_art,
                'duration_ms': 0,
                'external_url': yt_info.get('webpage_url') or youtube_url,
                'preview_url': None,
            }

        upsert_job(job_id, status="processing", message="Preparing download location...", stage="preparing",
                   progress=20)

        # Determine download path
        temp_dir = os.path.join(config.DOWNLOAD_DIR, "temp")
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        download_path = get_download_path(track_info, temp_dir, config.OUTPUT_FORMAT)

        upsert_job(job_id, status="processing", message="Downloading from YouTube...", stage="downloading", progress=40)
        download_result = youtube_service.download_by_video_id(video_id, download_path)
        if not download_result.get('success'):
            upsert_job(job_id, status="error",
                       message=f"Download failed: {download_result.get('error', 'Unknown error')}", progress=0)
            return

        upsert_job(job_id, status="processing", message="Applying metadata...", stage="tagging", progress=80)
        metadata_service.apply_metadata(download_result['file_path'], track_info)

        # Handle completion based on location
        if location == "navidrome":
            upsert_job(job_id, status="processing", message="Copying to Navidrome library...", stage="copying",
                       progress=90)
            try:
                target_path = navidrome_service.get_target_path(track_info, config.OUTPUT_FORMAT)
                shutil.copy2(download_result['file_path'], target_path)
                if os.path.exists(download_result['file_path']):
                    os.remove(download_result['file_path'])

                navidrome_result = navidrome_service.finalize_track(str(target_path))
                upsert_job(job_id,
                           status="completed",
                           message="Track successfully added to Navidrome library" if navidrome_result.get(
                               'success') else f"Track added to library (scan may need manual trigger): {navidrome_result.get('error', '')}",
                           file_path=str(target_path),
                           stage="completed",
                           progress=100,
                           )
                if track_id:
                    record_completed_download(track_id, metadata_provider)
            except Exception as e:
                upsert_job(job_id, status="error", message=f"Failed to copy to Navidrome: {str(e)}", progress=0)
        else:
            filename = os.path.basename(download_result['file_path'])
            encoded_filename = quote(filename, safe='')
            download_url = f"api/download/file/{job_id}?filename={encoded_filename}"
            upsert_job(job_id,
                       status="completed",
                       message="Track ready for download",
                       file_path=download_result['file_path'],
                       download_url=download_url,
                       stage="completed",
                       progress=100,
                       )

    except Exception as e:
        upsert_job(job_id, status="error", message=f"Error: {str(e)}", progress=0)


@app.post("/api/reverse/download")
async def reverse_download(request: ReverseDownloadRequest, background_tasks: BackgroundTasks):
    """Finalize reverse flow: download YouTube URL and tag with chosen track or manual metadata."""
    provider = resolve_metadata_provider(request.provider)
    get_metadata_service(provider)  # validate Spotify configured if needed

    location = request.location if request.location in ["local", "navidrome"] else "local"
    location_msg = "local downloads folder" if location == "local" else "Navidrome server"

    if request.spotify_track_id:
        dup = get_duplicate_download_reason(
            request.spotify_track_id, provider, location, config.OUTPUT_FORMAT
        )
        if dup:
            raise HTTPException(status_code=409, detail=dup)

    job_id = f"yt-{abs(hash((request.youtube_url, request.spotify_track_id or '', location, provider))) % 10_000_000}"

    upsert_job(
        job_id,
        status="queued",
        message=f"Reverse download queued for {location_msg}",
        progress=0,
        stage="queued",
        payload={"provider": provider, "record_track_id": request.spotify_track_id},
    )

    background_tasks.add_task(
        reverse_download_and_process,
        job_id,
        request.youtube_url,
        location,
        request.spotify_track_id,
        request.metadata,
        provider,
    )

    return {
        "status": "queued",
        "message": f"Reverse download started to {location_msg}",
        "job_id": job_id,
    }


@app.get("/api/download/status/{track_id}")
async def get_download_status(track_id: str):
    job = get_job(track_id)
    if not job:
        raise HTTPException(status_code=404, detail="Download not found")
    # Keep response shape compatible with old dict
    return {
        "status": job.get("status"),
        "message": job.get("message"),
        "stage": job.get("stage"),
        "progress": job.get("progress"),
        "file_path": job.get("file_path"),
        "download_url": job.get("download_url"),
        "error": job.get("error"),
    }


@app.post("/api/download/album")
async def download_album(request: AlbumDownloadRequest, background_tasks: BackgroundTasks):
    """Start downloading all tracks from an album"""

    provider = resolve_metadata_provider(request.provider)
    svc = get_metadata_service(provider)
    album_job_id = f"album:{request.album_id}"

    album = svc.get_album_details(request.album_id)

    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    # Validate location
    location = request.location if request.location in ["local", "navidrome"] else "local"
    location_msg = "local downloads folder" if location == "local" else "Navidrome server"

    output_format = request.format or config.OUTPUT_FORMAT
    to_queue = []
    for track in album["tracks"]:
        if get_duplicate_download_reason(track["id"], provider, location, output_format) is None:
            to_queue.append(track)

    if not to_queue:
        raise HTTPException(
            status_code=400,
            detail="All tracks in this album are already downloaded or still downloading.",
        )

    upsert_job(
        album_job_id,
        status="queued",
        message=f"Album '{album['name']}' queued",
        stage="queued",
        progress=0,
        album_id=request.album_id,
        payload={
            "album_id": request.album_id,
            "album_name": album["name"],
            "artist": album["artist"],
            "track_ids": [t["id"] for t in to_queue],
            "total_tracks": len(to_queue),
        },
    )

    for track in to_queue:
        upsert_job(
            track["id"],
            status="queued",
            message=f"Queued (Album: {album['name']})",
            progress=0,
            stage="queued",
            album_id=request.album_id,
            payload={"provider": provider, "record_track_id": track["id"]},
        )
        background_tasks.add_task(
            download_album_track,
            track["id"],
            location,
            request.album_id,
            request.format,
            request.quality,
            provider,
        )

    skipped = len(album["tracks"]) - len(to_queue)
    return {
        "status": "queued",
        "message": f"Queued {len(to_queue)} track(s) from '{album['name']}' to {location_msg}"
        + (f" ({skipped} skipped — already in library)" if skipped else ""),
        "album_id": request.album_id,
        "total_tracks": len(to_queue),
        "skipped_tracks": skipped,
        "queued_track_ids": [t["id"] for t in to_queue],
    }


def download_album_track(
    track_id: str,
    location: str,
    album_id: str,
    output_format: str = None,
    audio_quality: str = None,
    metadata_provider: str = "deezer",
):
    try:
        download_and_process(track_id, location, None, output_format, audio_quality, metadata_provider)
    except Exception as e:
        print(f"Error downloading album track {track_id}: {e}")



@app.get("/api/download/album/status/{album_id}")
async def get_album_download_status(album_id: str):
    album_job_id = f"album:{album_id}"
    meta_job = get_job(album_job_id)

    agg = get_album_aggregate(album_id, exclude_job_id=album_job_id)

    if not meta_job:
        # fallback: als iemand status opvraagt zonder dat album ooit gestart is
        raise HTTPException(status_code=404, detail="Album download not found")

    payload = meta_job.get("payload") or {}

    return {
        "status": agg["status"],
        "album_name": payload.get("album_name"),
        "artist": payload.get("artist"),
        "total_tracks": payload.get("total_tracks") or agg["total_tracks"],
        "completed_tracks": agg["completed_tracks"],
        "failed_tracks": agg["failed_tracks"],
        "current_track": agg["current_track"],
        "track_ids": payload.get("track_ids") or [],
    }



@app.get("/api/youtube/candidates/{track_id}")
async def get_youtube_candidates(track_id: str, provider: Optional[str] = Query(None)):
    """Get YouTube candidates for a track to let user choose if confidence is low"""
    p = resolve_metadata_provider(provider)
    svc = get_metadata_service(p)
    try:
        track_info = svc.get_track_details(track_id)
        if not track_info:
            raise HTTPException(status_code=404, detail="Track not found")

        result = youtube_service.search_candidates(
            track_info['name'],
            track_info['artist'],
            track_info
        )

        return {
            "track": {
                "id": track_id,
                "name": track_info['name'],
                "artist": track_info['artist'],
                "album": track_info.get('album', '')
            },
            **result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching YouTube: {str(e)}")


@app.get("/api/download/file/{track_id}")
async def download_file(track_id: str, filename: str = Query(...),
                        background_tasks: BackgroundTasks = BackgroundTasks()):
    """Download a file (for local browser downloads) and delete temp file afterward"""

    job = get_job(track_id)
    if not job:
        raise HTTPException(status_code=404, detail="Download not found")

    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="File not ready for download")

    file_path = job.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Decode URL-encoded filename for comparison
    decoded_filename = unquote(filename)
    actual_filename = os.path.basename(file_path)

    # Verify filename matches for security (compare decoded vs actual)
    if actual_filename != decoded_filename:
        raise HTTPException(status_code=400,
                            detail=f"Invalid filename. Expected: {actual_filename}, Got: {decoded_filename}")

    # Check if this is a temp file (for local downloads) - delete after serving
    # Normalize paths for comparison
    temp_dir_path = str(Path(config.DOWNLOAD_DIR) / "temp")
    is_temp_file = temp_dir_path in file_path or "temp" in os.path.dirname(file_path)

    # Return file for browser to download (saves to user's Downloads folder)
    # Use RFC 5987 encoding for non-ASCII filenames in Content-Disposition header
    # This handles special characters like ć, č, š, etc.
    ascii_filename = decoded_filename.encode('ascii', 'ignore').decode('ascii') or 'download.mp3'
    encoded_filename = quote(decoded_filename)

    response = FileResponse(
        file_path,
        media_type='audio/mpeg',
        filename=ascii_filename,  # Fallback ASCII filename
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
        }
    )

    # Delete temp file after download completes (only for local downloads)
    if is_temp_file:
        background_tasks.add_task(cleanup_temp_file, file_path, track_id)

    return response


def cleanup_temp_file(file_path: str, _job_id: str):
    """Clean up temporary download file after it's been served (local browser downloads).

    We do not record completed_track_downloads here — that table is for Navidrome
    library copies only (see download_and_process).
    """
    try:
        # Long delay so duplicate requests (extra tabs, extensions, browser retries) still hit the file
        time.sleep(max(2, config.TEMP_FILE_CLEANUP_DELAY_SEC))
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        print(f"Error cleaning up temp file {file_path}: {e}")


@app.get("/api/track/{track_id}/exists")
async def check_track_exists(
    track_id: str,
    provider: Optional[str] = Query(None),
    location: str = Query("local"),
):
    """Check if a track is already present (see below).

    - location=local: only files on this server (downloads/temp or downloads root).
      Does not use completed_track_downloads. Local browser saves go to the client PC.
    - location=navidrome: library file, DB completion record, or on-disk files here.
    """
    p = resolve_metadata_provider(provider)
    svc = get_metadata_service(p)
    try:
        if location not in ("local", "navidrome"):
            location = "local"

        track_info = svc.get_track_details(track_id)
        if not track_info:
            return {"exists": False, "file_path": None}

        ext = config.OUTPUT_FORMAT
        download_path = get_download_path(track_info, config.DOWNLOAD_DIR, ext)
        temp_path = get_download_path(
            track_info, os.path.join(config.DOWNLOAD_DIR, "temp"), ext
        )

        if location == "local":
            if os.path.isfile(download_path):
                return {"exists": True, "file_path": download_path}
            if os.path.isfile(temp_path):
                return {"exists": True, "file_path": temp_path}
            return {"exists": False, "file_path": None}

        # navidrome
        if has_completed_download(track_id, p):
            return {"exists": True, "file_path": None}
        if navidrome_service.track_file_exists(track_info, ext):
            return {"exists": True, "file_path": None}
        if os.path.isfile(download_path):
            return {"exists": True, "file_path": download_path}
        if os.path.isfile(temp_path):
            return {"exists": True, "file_path": temp_path}

        return {"exists": False, "file_path": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error checking track: {str(e)}")


@app.get("/api/formats")
async def get_available_formats():
    """Get available audio formats and quality options"""
    return {
        "formats": [
            {"value": "mp3", "label": "MP3", "description": "Compatible with most devices"},
            {"value": "m4a", "label": "M4A/AAC", "description": "Better quality, smaller files"},
            {"value": "opus", "label": "Opus", "description": "High quality, efficient compression"},
            {"value": "ogg", "label": "OGG Vorbis", "description": "Open source format"},
            {"value": "flac", "label": "FLAC", "description": "Lossless, larger files"}
        ],
        "qualities": [
            {"value": "96", "label": "96 kbps", "description": "Low quality, small files"},
            {"value": "128", "label": "128 kbps", "description": "Standard quality (default)"},
            {"value": "192", "label": "192 kbps", "description": "Good quality"},
            {"value": "256", "label": "256 kbps", "description": "High quality"},
            {"value": "320", "label": "320 kbps", "description": "Maximum quality"},
            {"value": "lossless", "label": "Lossless", "description": "FLAC only - no quality loss"}
        ],
        "default_format": config.OUTPUT_FORMAT,
        "default_quality": config.AUDIO_QUALITY
    }

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "default_metadata_provider": config.DEFAULT_METADATA_PROVIDER,
        "spotify_configured": spotify_service is not None,
        "navidrome_path": config.NAVIDROME_MUSIC_PATH,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)

