from pathlib import Path

import httpx
import pytest

from sceneseek.config import Settings
from sceneseek.main import create_app


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        frontend_dir=None,
        embedder="deterministic",
        clip_model="unused",
        device="cpu",
        frame_interval_seconds=1.0,
        max_upload_bytes=1024 * 1024,
        max_query_bytes=1024 * 1024,
        cors_origins=("http://localhost:5173",),
        native_library=None,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health(tmp_path: Path) -> None:
    transport = httpx.ASGITransport(app=create_app(make_settings(tmp_path)))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["indexed_videos"] == 0
        assert health.json()["model_loaded"] is False

@pytest.mark.anyio
async def test_upload_rejects_non_video(tmp_path: Path) -> None:
    transport = httpx.ASGITransport(app=create_app(make_settings(tmp_path)))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/videos", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        assert response.status_code == 415


@pytest.mark.anyio
async def test_private_catalog_and_media_are_session_isolated(tmp_path: Path):
    from sceneseek.security import owner_id
    from fastapi import Request
    app = create_app(make_settings(tmp_path))
    @app.post('/test-seed')
    def seed(request: Request):
        video_id = 'a' * 32
        app.state.database.create_video(video_id, 'Private', 'private.mp4', tmp_path / 'private.mp4', owner_id(request))
        app.state.database.create_job('b' * 32, video_id)
        return {'id': video_id}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as owner, httpx.AsyncClient(transport=transport, base_url='http://test') as stranger:
        video_id = (await owner.post('/test-seed')).json()['id']
        mine = (await owner.get('/api/videos')).json()
        assert len(mine) == 1 and 'owner_id' not in mine[0] and 'media_path' not in mine[0]
        assert (await stranger.get('/api/videos')).json() == []
        for path in [f'/api/videos/{video_id}/stream', f'/api/thumbnails/{video_id}/000001.jpg', '/api/jobs/' + 'b' * 32]:
            assert (await stranger.get(path)).status_code == 404
        assert (await stranger.delete(f'/api/videos/{video_id}')).status_code == 404
        assert (await owner.delete(f'/api/videos/{video_id}')).status_code == 409


@pytest.mark.anyio
async def test_cross_origin_writes_are_rejected(tmp_path: Path):
    transport = httpx.ASGITransport(app=create_app(make_settings(tmp_path)))
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        response = await client.post('/api/search/text', json={'query':'private'}, headers={'Origin':'https://evil.example'})
        assert response.status_code == 403
