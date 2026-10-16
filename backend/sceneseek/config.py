from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    frontend_dir: Path | None
    embedder: str
    clip_model: str
    device: str
    frame_interval_seconds: float
    max_upload_bytes: int
    max_query_bytes: int
    cors_origins: tuple[str, ...]
    native_library: Path | None
    max_pending_jobs: int = 2
    max_video_seconds: float = 600
    browser_playback: bool = False
    max_storage_bytes: int = 2 * 1024 ** 3
    clip_revision: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        model_id = os.getenv("SCENESEEK_CLIP_MODEL", "openai/clip-vit-base-patch32").strip()
        frontend = os.getenv("SCENESEEK_FRONTEND_DIR")
        native = os.getenv("SCENESEEK_NATIVE_LIBRARY")
        return cls(
            data_dir=Path(os.getenv("SCENESEEK_DATA_DIR", "./data")).resolve(),
            frontend_dir=Path(frontend).resolve() if frontend else None,
            embedder=os.getenv("SCENESEEK_EMBEDDER", "clip").strip().lower(),
            clip_model=model_id,
            device=os.getenv("SCENESEEK_DEVICE", "auto").strip().lower(),
            frame_interval_seconds=max(
                0.25, float(os.getenv("SCENESEEK_FRAME_INTERVAL_SECONDS", "2.0"))
            ),
            max_upload_bytes=int(os.getenv("SCENESEEK_MAX_UPLOAD_MB", "1024"))
            * 1024
            * 1024,
            max_query_bytes=int(os.getenv("SCENESEEK_MAX_QUERY_MB", "100"))
            * 1024
            * 1024,
            cors_origins=_csv(
                os.getenv("SCENESEEK_CORS_ORIGINS", "http://localhost:5173")
            ),
            native_library=Path(native).resolve() if native else None,
            max_pending_jobs=max(1, int(os.getenv("SCENESEEK_MAX_PENDING_JOBS", "2"))),
            max_video_seconds=float(os.getenv("SCENESEEK_MAX_VIDEO_SECONDS", "600")),
            browser_playback=os.getenv("SCENESEEK_BROWSER_PLAYBACK", "true").lower() == "true",
            max_storage_bytes=int(os.getenv("SCENESEEK_MAX_STORAGE_MB", "2048")) * 1024 ** 2,
            clip_revision=os.getenv("SCENESEEK_CLIP_REVISION") or (
                "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
                if model_id == "openai/clip-vit-base-patch32" else None
            ),
        )

    def prepare(self) -> None:
        for directory in (
            self.data_dir,
            self.upload_dir,
            self.index_dir,
            self.thumbnail_dir,
            self.temp_dir,
            self.playback_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "sceneseek.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "indexes"

    @property
    def thumbnail_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def playback_dir(self) -> Path:
        return self.data_dir / "playback"

