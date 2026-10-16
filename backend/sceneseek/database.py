from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    media_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_seconds REAL,
                    frame_count INTEGER,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_video_id_idx ON jobs(video_id);
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(videos)")}
            for name in ("owner_id", "playback_path"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE videos ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")

    def create_video(
        self, video_id: str, display_name: str, original_filename: str, media_path: Path,
        owner_id: str = "",
    ) -> dict[str, Any]:
        now = _now()
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO videos (
                    id, display_name, original_filename, media_path, status,
                    created_at, updated_at, owner_id
                ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (video_id, display_name, original_filename, str(media_path), now, now, owner_id),
            )
        return self.get_video(video_id)

    def update_video(self, video_id: str, **fields: Any) -> None:
        allowed = {"display_name", "status", "duration_seconds", "frame_count", "error", "playback_path"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._write_lock, self._connect() as connection:
            connection.execute(
                f"UPDATE videos SET {assignments} WHERE id = ?",
                (*updates.values(), video_id),
            )

    def get_video(self, video_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM videos WHERE id = ?", (video_id,)
            ).fetchone()
        if row is None:
            raise KeyError(video_id)
        return dict(row)

    def list_videos(self, owner_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM videos WHERE (? IS NULL OR owner_id = ?) ORDER BY created_at DESC",
                (owner_id, owner_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_video(self, video_id: str) -> dict[str, Any]:
        video = self.get_video(video_id)
        with self._write_lock, self._connect() as connection:
            connection.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        return video

    def create_job(self, job_id: str, video_id: str) -> dict[str, Any]:
        now = _now()
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, video_id, status, progress, message, created_at, updated_at
                ) VALUES (?, ?, 'queued', 0, 'Waiting to index', ?, ?)
                """,
                (job_id, video_id, now, now),
            )
        return self.get_job(job_id)

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {"status", "progress", "message", "error"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._write_lock, self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                (*updates.values(), job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def fail_interrupted_jobs(self) -> None:
        now = _now()
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'failed', progress = 0, error = 'Server restarted during indexing',
                    message = 'Indexing was interrupted; upload the video again', updated_at = ?
                WHERE status IN ('queued', 'processing')
                """,
                (now,),
            )
            connection.execute(
                """
                UPDATE videos
                SET status = 'failed', error = 'Server restarted during indexing', updated_at = ?
                WHERE status IN ('queued', 'processing')
                """,
                (now,),
            )

