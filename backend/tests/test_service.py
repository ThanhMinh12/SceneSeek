from pathlib import Path

import cv2
import numpy as np

from sceneseek.catalog import Catalog
from sceneseek.config import Settings
from sceneseek.database import Database
from sceneseek.embeddings import LazyEmbedder
from sceneseek.native import SimilarityIndex
from sceneseek.service import SceneSeekService


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(
        data_dir=tmp_path,
        frontend_dir=None,
        embedder="deterministic",
        clip_model="unused",
        device="cpu",
        frame_interval_seconds=0.25,
        max_upload_bytes=10 * 1024 * 1024,
        max_query_bytes=10 * 1024 * 1024,
        cors_origins=(),
        native_library=None,
    )
    settings.prepare()
    return settings


def _write_red_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 8.0, (96, 64)
    )
    assert writer.isOpened()
    try:
        for frame_number in range(16):
            frame = np.zeros((64, 96, 3), dtype=np.uint8)
            frame[:, :] = (0, 0, 220)
            cv2.putText(
                frame,
                str(frame_number),
                (8, 38),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )
            writer.write(frame)
    finally:
        writer.release()


def test_video_is_indexed_and_searchable(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings.database_path)
    native = SimilarityIndex()
    catalog = Catalog(settings.index_dir, database, native)
    service = SceneSeekService(
        settings,
        database,
        catalog,
        LazyEmbedder("deterministic", "unused", "cpu"),
    )
    video_path = settings.upload_dir / "red-scene.avi"
    _write_red_video(video_path)
    database.create_video("video-1", "Red scene", "red-scene.avi", video_path)
    database.create_job("job-1", "video-1")

    service.index_video("job-1", "video-1")

    assert database.get_job("job-1")["status"] == "complete"
    assert database.get_video("video-1")["frame_count"] >= 4
    results = service.text_search("red", 3)
    assert results
    assert results[0]["video_id"] == "video-1"
    assert results[0]["score"] > 0

