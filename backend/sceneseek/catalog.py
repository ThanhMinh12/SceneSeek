"""Authorization/catalog adapter around the native C++ retrieval engine."""
from __future__ import annotations

import re
import threading
from pathlib import Path

from .database import Database
from .engine import NativeEngine
from .native import SimilarityIndex
from .reference_catalog import ReferenceCatalog


class Catalog:
    def __init__(self, index_dir: Path, database: Database, index: SimilarityIndex,
                 *, cache_bytes: int = 64*1024**2, workers: int = 2):
        self.index_dir, self.database, self.index = index_dir, database, index
        self._reference = ReferenceCatalog(index_dir, database, index)
        self._migration_lock = threading.RLock()
        self.engine = NativeEngine(index._library, index_dir, cache_bytes, workers) if index.backend == 'cpp' else None

    @property
    def backend(self):
        return 'cpp' if self.engine is not None else 'numpy'

    @staticmethod
    def _validate_id(video_id):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', video_id):
            raise ValueError('Invalid video id')

    def save(self, video_id, embeddings, timestamps, thumbnail_names, embedder_name):
        self._validate_id(video_id)
        if self.engine:
            self.engine.save(video_id, embeddings, timestamps, thumbnail_names, embedder_name)
        else:
            self._reference.save(video_id, embeddings, timestamps, thumbnail_names, embedder_name)

    def _authorized_videos(self, owner_id):
        videos = [video for video in self.database.list_videos(owner_id) if video['status'] == 'ready']
        for video in videos:
            video_id = video['id']
            self._validate_id(video_id)
            native = self.index_dir / f'{video_id}.ssidx'
            legacy = self.index_dir / f'{video_id}.npz'
            if self.engine and not native.exists() and legacy.is_file():
                # Migrate only authorized shards, retaining the legacy archive.
                try:
                    with self._migration_lock:
                        self.database.get_video(video_id)  # A concurrent deletion must not resurrect a shard.
                        if not native.exists() and legacy.is_file():
                            values = self._reference._load(video_id)
                            self.engine.save(video_id, values['embeddings'], values['timestamps'],
                                             values['thumbnails'].tolist(), str(values['embedder'].item()))
                except (OSError, ValueError, KeyError):
                    continue
            if not self.engine and native.exists():
                raise RuntimeError('This library uses native indexes. Build the SceneSeek C++ engine before searching.')
        return videos

    @staticmethod
    def _result(video, match):
        video_id = video['id']
        return {'video_id': video_id, 'title': video['display_name'],
                'timestamp_seconds': match.timestamp_seconds, 'end_seconds': match.end_seconds,
                'score': float(match.score), 'playback_rate': float(match.playback_rate),
                'thumbnail_url': f'/api/thumbnails/{video_id}/{match.thumbnail.decode("utf-8")}',
                'video_url': f'/api/videos/{video_id}/stream'}

    def search_frames(self, query, embedder_name, top_k, owner_id=None):
        videos = self._authorized_videos(owner_id)
        if not self.engine:
            return self._reference.search_frames(query, embedder_name, top_k, owner_id)
        return [self._result(video, match) for video, match in self.engine.search(query, embedder_name, videos, top_k)]

    def search_sequence(self, query, embedder_name, top_k, *, query_timestamps=None, query_duration=None, owner_id=None):
        videos = self._authorized_videos(owner_id)
        if not self.engine:
            return self._reference.search_sequence(query, embedder_name, top_k,
                query_timestamps=query_timestamps, query_duration=query_duration, owner_id=owner_id)
        return [self._result(video, match) for video, match in self.engine.search(query,
            embedder_name, videos, top_k, timestamps=query_timestamps,
            duration=query_duration, sequence=True)]

    def remove(self, video_id):
        self._validate_id(video_id)
        with self._migration_lock:
            if self.engine:
                self.engine.remove(video_id)
            self._reference.remove(video_id)
