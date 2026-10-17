"""Bounded, ephemeral per-session adapters around the real SceneSeek service."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import replace
from pathlib import Path

from PIL import Image
from sceneseek.catalog import Catalog
from sceneseek.config import Settings
from sceneseek.database import Database
from sceneseek.native import SimilarityIndex
from sceneseek.service import SceneSeekService


class DemoSessions:
    def __init__(self, root: Path, embedder, native: Path, max_sessions: int = 12):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.native = native
        self.max_sessions = max_sessions
        self.lock = threading.RLock()

    @staticmethod
    def new() -> str:
        return uuid.uuid4().hex

    def path(self, session: str) -> Path:
        if not isinstance(session, str) or not re.fullmatch(r"[a-f0-9]{32}", session):
            raise ValueError("This demo session expired. Reload the page.")
        return self.root / session

    def delete(self, session: str) -> None:
        with self.lock:
            path = self.path(session)
            if path.exists():
                shutil.rmtree(path)

    def service(self, session: str) -> SceneSeekService:
        with self.lock:
            path = self.path(session)
            if not path.exists() and sum(p.is_dir() for p in self.root.iterdir()) >= self.max_sessions:
                raise ValueError("The free demo is busy. Please try again later.")
            settings = replace(
                Settings.from_env(), data_dir=path, frame_interval_seconds=1.0,
                max_video_seconds=60, browser_playback=True, native_library=self.native,
            )
            settings.prepare()
            database = Database(settings.database_path)
            index = SimilarityIndex(self.native)
            if index.backend != "cpp":
                raise RuntimeError("The native retrieval library did not load")
            return SceneSeekService(settings, database, Catalog(settings.index_dir, database, index), self.embedder)

    def index(self, session: str, filename: str):
        if not filename:
            raise ValueError("Choose a video first.")
        source = Path(filename)
        if not source.is_file() or not 0 < source.stat().st_size <= 40 * 1024**2:
            raise ValueError("Choose a non-empty video smaller than 40 MB.")
        service = self.service(session)
        if len(service.database.list_videos()) >= 3:
            raise ValueError("Three videos per session. Clear the library to start again.")
        if sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()) > 2 * 1024**3:
            raise ValueError("The free demo storage is full. Please try again later.")
        video_id, job_id = uuid.uuid4().hex, uuid.uuid4().hex
        destination = service.settings.upload_dir / f"{video_id}{source.suffix.lower()}"
        shutil.copyfile(source, destination)
        service.database.create_video(video_id, source.stem[:100], source.name[:150], destination, session)
        service.database.create_job(job_id, video_id)
        service.index_video(job_id, video_id)
        video = service.database.get_video(video_id)
        if video['status'] != 'ready':
            message = video.get('error') or 'Indexing failed.'
            service.delete_video(video_id)
            raise ValueError(message)
        rows = [[v['display_name'], round(v['duration_seconds'], 2), v['frame_count']]
                for v in service.database.list_videos(session)]
        return rows, video['playback_path'], f"Indexed {video['frame_count']} moments. Search below."

    def search(self, session: str, kind: str, query):
        service = self.service(session)
        if not service.database.list_videos(session):
            raise ValueError("Index a video before searching.")
        if kind == 'text':
            if not isinstance(query, str) or not query.strip() or len(query) > 500:
                raise ValueError("Enter a description of 1–500 characters.")
            matches = service.text_search(query.strip(), 3, session)
        elif kind == 'image':
            if not query:
                raise ValueError("Choose an image first.")
            matches = service.image_search(Path(query), 3, session)
        elif kind == 'clip':
            if not query or Path(query).stat().st_size > 40 * 1024**2:
                raise ValueError("Choose a reference clip smaller than 40 MB.")
            matches = service.clip_search(Path(query), 3, session)
        else:
            raise ValueError("Unknown search type")
        gallery, rows = [], []
        for match in matches:
            thumbnail = service.settings.thumbnail_dir / match['video_id'] / match['thumbnail_url'].rsplit('/', 1)[1]
            with Image.open(thumbnail) as image:
                gallery.append((image.copy(), f"{match['title']} · {match['timestamp_seconds']:.1f}s · {match['playback_rate']:g}×"))
            rows.append([match['title'], round(match['timestamp_seconds'], 2), round(match['end_seconds'], 2), match['playback_rate'], round(match['score'], 4)])
        preview = None
        if matches:
            best = matches[0]
            video = service.database.get_video(best['video_id'])
            preview = service.settings.temp_dir / 'match.webm'
            subprocess.run([
                os.getenv('SCENESEEK_FFMPEG') or 'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                '-ss', str(best['timestamp_seconds']), '-i', video['playback_path'],
                '-t', str(max(0.1, best['end_seconds'] - best['timestamp_seconds'])),
                '-c:v', 'libvpx', '-deadline', 'realtime', '-cpu-used', '8',
                '-threads', '1', '-an', str(preview),
            ], check=True, capture_output=True, timeout=90)
        return gallery, rows, str(preview) if preview else None, f"{len(matches)} matches. Similarity scores are not probabilities."
