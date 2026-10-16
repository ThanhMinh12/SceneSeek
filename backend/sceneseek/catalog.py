from __future__ import annotations

from pathlib import Path
from functools import lru_cache
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .database import Database
from .native import SimilarityIndex


FloatArray = NDArray[np.float32]


class Catalog:
    def __init__(self, index_dir: Path, database: Database, index: SimilarityIndex):
        self.index_dir = index_dir
        self.database = database
        self.index = index

    def save(
        self,
        video_id: str,
        embeddings: FloatArray,
        timestamps: list[float],
        thumbnail_names: list[str],
        embedder_name: str,
    ) -> None:
        destination = self.index_dir / f"{video_id}.npz"
        temporary = destination.with_suffix(".npz.tmp")
        with temporary.open("wb") as handle:
            np.savez_compressed(
                handle,
                embeddings=np.asarray(embeddings, dtype=np.float32),
                timestamps=np.asarray(timestamps, dtype=np.float32),
                thumbnails=np.asarray(thumbnail_names),
                embedder=np.asarray(embedder_name),
            )
        temporary.replace(destination)
        self._load.cache_clear()

    @lru_cache(maxsize=32)
    def _load(self, video_id: str) -> dict[str, Any]:
        path = self.index_dir / f"{video_id}.npz"
        with np.load(path, allow_pickle=False) as values:
            return {key: values[key].copy() for key in values.files}

    def search_frames(
        self,
        query: FloatArray,
        embedder_name: str,
        top_k: int,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        videos = [video for video in self.database.list_videos(owner_id) if video["status"] == "ready"]
        candidates: list[tuple[float, dict[str, Any], float, str]] = []
        for video in videos:
            try:
                data = self._load(video["id"])
            except (FileNotFoundError, ValueError):
                continue
            if str(data["embedder"].item()) != embedder_name:
                continue
            embeddings = np.asarray(data["embeddings"], dtype=np.float32)
            # Search each immutable shard independently. Do not concatenate the
            # entire library into a second, potentially multi-GB matrix.
            for frame, score in self.index.top_k(query, embeddings, min(len(embeddings), top_k * 16)):
                candidates.append((score, video, float(data["timestamps"][frame]), str(data["thumbnails"][frame])))
        candidates.sort(key=lambda value: (-value[0], value[1]["id"], value[2]))
        results: list[dict[str, Any]] = []
        selected: dict[str, list[float]] = {}
        for score, video, timestamp, thumbnail in candidates:
            prior = selected.setdefault(video["id"], [])
            if any(abs(timestamp - previous) < 3.0 for previous in prior):
                continue
            prior.append(timestamp)
            results.append(
                {
                    "video_id": video["id"],
                    "title": video["display_name"],
                    "timestamp_seconds": timestamp,
                    "end_seconds": min(
                        timestamp + 4.0, float(video["duration_seconds"] or timestamp + 4)
                    ),
                    "score": score,
                    "playback_rate": 1.0,
                    "thumbnail_url": f"/api/thumbnails/{video['id']}/{thumbnail}",
                    "video_url": f"/api/videos/{video['id']}/stream",
                }
            )
            if len(results) >= top_k:
                break
        return results

    def search_sequence(
        self,
        query: FloatArray,
        embedder_name: str,
        top_k: int,
        *,
        query_timestamps: list[float] | None = None,
        query_duration: float | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for video in self.database.list_videos(owner_id):
            if video["status"] != "ready":
                continue
            try:
                data = self._load(video["id"])
            except (FileNotFoundError, ValueError):
                continue
            if str(data["embedder"].item()) != embedder_name:
                continue
            timestamps = data["timestamps"]
            thumbnails = data["thumbnails"]
            target = np.asarray(data["embeddings"], dtype=np.float32)
            if len(timestamps) < 2:
                continue
            interval = float(np.median(np.diff(timestamps)))
            query_times = np.asarray(
                query_timestamps if query_timestamps is not None
                else np.arange(len(query)) * interval, dtype=np.float64,
            )
            duration = query_duration if query_duration is not None else len(query) * interval
            best = None
            # Rate means target seconds per query second, not frame-index spacing.
            # Resample the query onto each target's actual temporal grid. A 1x
            # query then compares corresponding frames even when ingestion and
            # query sampling intervals differ. Prefer 1x on equal scores.
            for rate in (1.0, 0.5, 0.75, 1.25, 1.5, 2.0):
                # Ignore tiny codec-padding tails; they are not another full
                # sampled moment at the end of the reference.
                sample_times = np.arange(0, duration - min(0.1, interval / rate * 0.1), interval / rate)
                if len(sample_times) < 3:
                    continue
                resampled = np.column_stack([
                    np.interp(sample_times, query_times, query[:, dimension])
                    for dimension in range(query.shape[1])
                ]).astype(np.float32)
                latest_start = float(video["duration_seconds"]) - duration * rate
                valid_starts = int(np.searchsorted(timestamps, latest_start + 1e-5, side="right"))
                if valid_starts <= 0:
                    continue
                searchable = target[:valid_starts + len(resampled) - 1]
                match = self.index.best_sequence(resampled, searchable, rates=(1.0,))
                if match is not None and (best is None or match[0] > best[0] + 1e-6):
                    best = (match[0], match[1], rate)
            if best is None:
                continue
            score, start, rate = best
            matches.append(
                {
                    "video_id": video["id"],
                    "title": video["display_name"],
                    "timestamp_seconds": float(timestamps[start]),
                    "end_seconds": min(float(video["duration_seconds"]), float(timestamps[start]) + duration * rate),
                    "score": score,
                    "playback_rate": rate,
                    "thumbnail_url": f"/api/thumbnails/{video['id']}/{thumbnails[start]}",
                    "video_url": f"/api/videos/{video['id']}/stream",
                }
            )
        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[:top_k]

    def remove(self, video_id: str) -> None:
        (self.index_dir / f"{video_id}.npz").unlink(missing_ok=True)
        self._load.cache_clear()

