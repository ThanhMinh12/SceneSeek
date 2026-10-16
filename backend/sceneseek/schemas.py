from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    similarity_backend: Literal["cpp", "numpy"]
    embedder: str
    model_loaded: bool
    indexed_videos: int


class TextSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=12, ge=1, le=50)


class SearchResult(BaseModel):
    video_id: str
    title: str
    timestamp_seconds: float
    end_seconds: float
    score: float
    playback_rate: float
    thumbnail_url: str
    video_url: str


class SearchResponse(BaseModel):
    query_type: Literal["text", "image", "clip"]
    elapsed_ms: float
    results: list[SearchResult]

