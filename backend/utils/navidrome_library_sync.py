"""
Periodically scan NAVIDROME_MUSIC_PATH and match files to catalog tracks via tags,
then record completed_track_downloads so the UI / duplicate checks stay in sync.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
from utils.job_store import record_completed_download

AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".wav", ".aac", ".wma"}
)


def _norm(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _first_tag_value(audio: Any, keys: Tuple[str, ...]) -> Optional[str]:
    for k in keys:
        if k not in audio:
            continue
        v = audio[k]
        if isinstance(v, list):
            for item in v:
                if item is None:
                    continue
                if hasattr(item, "text") and item.text:
                    return str(item.text[0]).strip()
                s = str(item).strip()
                if s:
                    return s
        elif hasattr(v, "text") and v.text:
            return str(v.text[0]).strip()
        else:
            s = str(v).strip()
            if s:
                return s
    return None


def read_artist_title(path: Path) -> Optional[Tuple[str, str]]:
    """Read (artist, title) from tags, with filename fallback."""
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(path))
    except Exception:
        audio = None
    if audio is None:
        return _parse_filename_stem(path)

    artist = _first_tag_value(
        audio,
        (
            "TPE1",
            "TPE2",
            "TXXX:artist",
            "artist",
            "ARTIST",
            "Album Artist",
            "albumartist",
            "©ART",
        ),
    )
    title = _first_tag_value(
        audio,
        ("TIT2", "title", "TITLE", "TXXX:title", "©nam"),
    )

    tags = getattr(audio, "tags", None)
    if tags:
        if not artist and "TPE1" in tags:
            try:
                artist = str(tags["TPE1"].text[0]).strip()
            except Exception:
                pass
        if not title and "TIT2" in tags:
            try:
                title = str(tags["TIT2"].text[0]).strip()
            except Exception:
                pass

    if not artist or not title:
        parsed = _parse_filename_stem(path)
        if parsed:
            if not artist:
                artist = parsed[0]
            if not title:
                title = parsed[1]
    if artist and title:
        return (artist.strip(), title.strip())
    return None


def _parse_filename_stem(path: Path) -> Optional[Tuple[str, str]]:
    stem = path.stem
    if " - " in stem:
        a, t = stem.split(" - ", 1)
        a, t = a.strip(), t.strip()
        if a and t:
            return (a, t)
    return None


def iter_audio_files(root: Path):
    if not root.is_dir():
        return
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS:
            yield p


def _best_catalog_id(
    hits: List[Dict[str, Any]], artist: str, title: str
) -> Optional[str]:
    if not hits:
        return None
    na, nt = _norm(artist), _norm(title)
    best_id = None
    best_score = -1
    for h in hits:
        ha = _norm(h.get("artist") or "")
        ht = _norm(h.get("name") or "")
        score = 0
        if nt and ht:
            if nt == ht:
                score += 100
            elif nt in ht or ht in nt:
                score += 60
        if na and ha:
            if na == ha:
                score += 80
            elif na in ha or ha in na:
                score += 40
        if score > best_score:
            best_score = score
            best_id = h.get("id")
    if best_score >= 45 and best_id:
        return str(best_id)
    # Fallback: first search hit (still rate-limited; may mis-match obscure tracks)
    if hits:
        return str(hits[0].get("id") or "")
    return None


def run_navidrome_library_sync(deezer_service: Any, spotify_service: Any = None) -> None:
    root = Path(config.NAVIDROME_MUSIC_PATH)
    if not root.is_dir():
        print(f"Navidrome library sync: skip (not a directory): {root}")
        return

    files = list(iter_audio_files(root))
    if not files:
        print("Navidrome library sync: no audio files found")
        return

    deezer_ok = 0
    spotify_ok = 0
    failed = 0

    for path in files:
        meta = read_artist_title(path)
        if not meta:
            failed += 1
            continue
        artist, title = meta
        try:
            hits = deezer_service.search_tracks(f"{artist} {title}", limit=15)
            did = _best_catalog_id(hits, artist, title)
            if did:
                record_completed_download(did, "deezer")
                deezer_ok += 1
        except Exception as e:
            print(f"Navidrome sync Deezer error ({path.name}): {e}")

        if spotify_service is not None:
            try:
                shits = spotify_service.search_tracks(f"{artist} {title}", limit=15)
                sid = _best_catalog_id(shits, artist, title)
                if sid:
                    record_completed_download(sid, "spotify")
                    spotify_ok += 1
            except Exception as e:
                print(f"Navidrome sync Spotify error ({path.name}): {e}")

        time.sleep(float(config.NAVIDROME_SYNC_API_DELAY_SEC))

    print(
        f"Navidrome library sync: scanned {len(files)} files, "
        f"Deezer rows {deezer_ok}, Spotify rows {spotify_ok}, no tags/filename {failed}"
    )


def start_navidrome_library_sync_background(deezer_service: Any, spotify_service: Any) -> None:
    if not config.NAVIDROME_SYNC_ENABLED:
        print("Navidrome library sync: disabled (NAVIDROME_SYNC_ENABLED)")
        return

    interval_sec = max(3600, int(config.NAVIDROME_SYNC_INTERVAL_HOURS * 3600))
    initial_delay = int(config.NAVIDROME_SYNC_INITIAL_DELAY_SEC)

    def runner() -> None:
        time.sleep(initial_delay)
        while True:
            try:
                run_navidrome_library_sync(deezer_service, spotify_service)
            except Exception as e:
                print(f"Navidrome library sync run failed: {e}")
            time.sleep(interval_sec)

    t = threading.Thread(target=runner, daemon=True, name="navidrome-library-sync")
    t.start()
    print(
        f"Navidrome library sync: background thread started "
        f"(first run after {initial_delay}s, then every {interval_sec // 3600}h)"
    )
