import os
import sqlite3
import json
import time
from typing import Any, Dict, Optional

import config

JOBS_DB_PATH = os.path.join(config.DOWNLOAD_DIR, "jobs.db")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(JOBS_DB_PATH, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl_sql: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl_sql}")


def init_jobs_db() -> None:
    conn = _db()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS download_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            stage TEXT,
            progress INTEGER,
            message TEXT,
            file_path TEXT,
            download_url TEXT,
            error TEXT,
            album_id TEXT,
            payload_json TEXT,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        )
        """)

        # If the table existed before album_id was added, migrate in-place.
        _ensure_column(conn, "download_jobs", "album_id", "TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_download_jobs_status ON download_jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_download_jobs_updated ON download_jobs(updated_at_ms)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_download_jobs_album_id ON download_jobs(album_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS completed_track_downloads (
            track_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            completed_at_ms INTEGER NOT NULL,
            PRIMARY KEY (track_id, provider)
        )
        """)
        conn.commit()
    finally:
        conn.close()


def upsert_job(
    job_id: str,
    *,
    status: str,
    message: str,
    stage: Optional[str] = None,
    progress: Optional[int] = None,
    file_path: Optional[str] = None,
    download_url: Optional[str] = None,
    error: Optional[str] = None,
    album_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    now = _now_ms()
    conn = _db()
    try:
        conn.execute("""
        INSERT INTO download_jobs (
            job_id, status, stage, progress, message, file_path, download_url, error,
            album_id, payload_json, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            status=excluded.status,
            stage=COALESCE(excluded.stage, download_jobs.stage),
            progress=COALESCE(excluded.progress, download_jobs.progress),
            message=excluded.message,
            file_path=COALESCE(excluded.file_path, download_jobs.file_path),
            download_url=COALESCE(excluded.download_url, download_jobs.download_url),
            error=COALESCE(excluded.error, download_jobs.error),
            album_id=COALESCE(excluded.album_id, download_jobs.album_id),
            payload_json=COALESCE(excluded.payload_json, download_jobs.payload_json),
            updated_at_ms=excluded.updated_at_ms
        """, (
            job_id, status, stage, progress, message, file_path, download_url, error,
            album_id,
            json.dumps(payload) if payload is not None else None,
            now, now
        ))
        conn.commit()
    finally:
        conn.close()


def record_completed_download(track_id: str, provider: str) -> None:
    """Mark a catalog track as already downloaded (survives temp file cleanup)."""
    now = _now_ms()
    conn = _db()
    try:
        conn.execute(
            """
            INSERT INTO completed_track_downloads (track_id, provider, completed_at_ms)
            VALUES (?, ?, ?)
            ON CONFLICT(track_id, provider) DO UPDATE SET completed_at_ms = excluded.completed_at_ms
            """,
            (track_id, provider, now),
        )
        conn.commit()
    finally:
        conn.close()


def has_completed_download(track_id: str, provider: str) -> bool:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT 1 FROM completed_track_downloads WHERE track_id = ? AND provider = ?",
            (track_id, provider),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT * FROM download_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            return None

        d = dict(row)
        payload_json = d.pop("payload_json", None)
        if payload_json:
            try:
                d["payload"] = json.loads(payload_json)
            except Exception:
                d["payload"] = None
        else:
            d["payload"] = None

        return d
    finally:
        conn.close()

def get_album_track_jobs(album_id: str, *, exclude_job_id: Optional[str] = None) -> list[dict]:
    conn = _db()
    try:
        sql = """
        SELECT job_id, status, stage, progress, message, file_path, download_url, error, updated_at_ms
        FROM download_jobs
        WHERE album_id = ?
        """
        params = [album_id]
        if exclude_job_id:
            sql += " AND job_id <> ?"
            params.append(exclude_job_id)

        sql += " ORDER BY updated_at_ms DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_album_aggregate(album_id: str, *, exclude_job_id: Optional[str] = None) -> dict:
    conn = _db()
    try:
        where = "album_id = ?"
        params: list = [album_id]
        if exclude_job_id:
            where += " AND job_id <> ?"
            params.append(exclude_job_id)

        total = conn.execute(f"SELECT COUNT(*) AS n FROM download_jobs WHERE {where}", params).fetchone()["n"]
        completed = conn.execute(
            f"SELECT COUNT(*) AS n FROM download_jobs WHERE {where} AND status = 'completed'",
            params,
        ).fetchone()["n"]
        failed = conn.execute(
            f"SELECT COUNT(*) AS n FROM download_jobs WHERE {where} AND status = 'error'",
            params,
        ).fetchone()["n"]

        current = conn.execute(
            f"""
            SELECT job_id
            FROM download_jobs
            WHERE {where} AND status NOT IN ('completed', 'error')
            ORDER BY updated_at_ms DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        current_track = current["job_id"] if current else None

        status = "completed" if total > 0 and (completed + failed) >= total else "downloading"

        return {
            "status": status,
            "total_tracks": total,
            "completed_tracks": completed,
            "failed_tracks": failed,
            "current_track": current_track,
        }
    finally:
        conn.close()
