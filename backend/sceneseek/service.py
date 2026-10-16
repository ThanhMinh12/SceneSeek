from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from .catalog import Catalog
from .config import Settings
from .database import Database
from .embeddings import LazyEmbedder
from .media import browser_video, extract_frames


class SceneSeekService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        catalog: Catalog,
        embedder: LazyEmbedder,
    ):
        self.settings = settings
        self.database = database
        self.catalog = catalog
        self.embedder = embedder

    def index_video(self, job_id: str, video_id: str) -> None:
        video = self.database.get_video(video_id)
        thumbnail_dir = self.settings.thumbnail_dir / video_id
        try:
            self.database.update_video(video_id, status="processing", error=None)
            self.database.update_job(
                job_id, status="processing", progress=0.08, message="Reading video frames"
            )
            frames = extract_frames(
                Path(video["media_path"]),
                self.settings.frame_interval_seconds,
                thumbnail_dir,
                max_frames=1200,
                max_duration=self.settings.max_video_seconds,
            )
            if self.settings.browser_playback:
                playback = self.settings.playback_dir / f"{video_id}.webm"
                browser_video(Path(video["media_path"]), playback, frames.duration_seconds)
                self.database.update_video(video_id, playback_path=str(playback))
            self.database.update_job(
                job_id,
                progress=0.45,
                message=f"Embedding {len(frames.images)} sampled frames",
            )
            model = self.embedder.get()
            batches = []
            batch_size = 32
            for start in range(0, len(frames.images), batch_size):
                batches.append(model.embed_images(frames.images[start : start + batch_size]))
                progress = 0.45 + 0.45 * min(
                    1.0, (start + batch_size) / len(frames.images)
                )
                self.database.update_job(job_id, progress=progress)

            import numpy as np

            embeddings = np.concatenate(batches, axis=0)
            self.catalog.save(
                video_id,
                embeddings,
                frames.timestamps,
                frames.thumbnail_names,
                model.name,
            )
            self.database.update_video(
                video_id,
                status="ready",
                duration_seconds=frames.duration_seconds,
                frame_count=len(frames.images),
                error=None,
            )
            self.database.update_job(
                job_id,
                status="complete",
                progress=1.0,
                message=f"Indexed {len(frames.images)} searchable moments",
                error=None,
            )
        except Exception as exc:  # Background tasks must persist their own failure.
            shutil.rmtree(thumbnail_dir, ignore_errors=True)
            self.catalog.remove(video_id)
            message = str(exc) or exc.__class__.__name__
            self.database.update_video(video_id, status="failed", error=message)
            self.database.update_job(
                job_id,
                status="failed",
                progress=0,
                message="Indexing failed",
                error=message,
            )

    def text_search(self, query: str, top_k: int, owner_id: str | None = None) -> list[dict[str, Any]]:
        model = self.embedder.get()
        vector = model.embed_text([query])[0]
        return self.catalog.search_frames(vector, model.name, top_k, owner_id)

    def image_search(self, image_path: Path, top_k: int, owner_id: str | None = None) -> list[dict[str, Any]]:
        model = self.embedder.get()
        with Image.open(image_path) as image:
            if image.width * image.height > 16_000_000:
                raise ValueError("Query images must contain at most 16 megapixels")
            vector = model.embed_images([image.convert("RGB")])[0]
        return self.catalog.search_frames(vector, model.name, top_k, owner_id)

    def clip_search(self, clip_path: Path, top_k: int, owner_id: str | None = None) -> list[dict[str, Any]]:
        frames = extract_frames(
            clip_path,
            min(0.5, self.settings.frame_interval_seconds / 2),
            max_frames=241,
            max_duration=60,
        )
        if not 4 <= frames.duration_seconds <= 60:
            raise ValueError("Reference clips must be between 4 and 60 seconds long")
        model = self.embedder.get()
        import numpy as np

        embeddings = np.concatenate([
            model.embed_images(frames.images[start:start + 32])
            for start in range(0, len(frames.images), 32)
        ])
        return self.catalog.search_sequence(
            embeddings, model.name, top_k,
            query_timestamps=frames.timestamps,
            query_duration=frames.duration_seconds,
            owner_id=owner_id,
        )

    def delete_video(self, video_id: str) -> None:
        video = self.database.delete_video(video_id)
        Path(video["media_path"]).unlink(missing_ok=True)
        if video.get("playback_path"):
            Path(video["playback_path"]).unlink(missing_ok=True)
        shutil.rmtree(self.settings.thumbnail_dir / video_id, ignore_errors=True)
        self.catalog.remove(video_id)

