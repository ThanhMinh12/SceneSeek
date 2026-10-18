from __future__ import annotations

import re
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .catalog import Catalog
from .config import Settings
from .database import Database
from .embeddings import LazyEmbedder
from .native import SimilarityIndex
from .schemas import HealthResponse, SearchResponse, TextSearchRequest
from .service import SceneSeekService
from .security import install_security, owner_id
from .dispatch import DispatchRegistry
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _safe_display_name(filename: str) -> str:
    stem = Path(filename).stem.strip()
    cleaned = re.sub(r"[^\w .()\-]", "", stem, flags=re.UNICODE).strip()
    return cleaned[:120] or "Untitled video"


async def _save_upload(upload: UploadFile, destination: Path, limit: int) -> int:
    written = 0
    try:
        with destination.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(status_code=413, detail="Uploaded file is too large")
                handle.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return written


class DispatchCancellation(BaseModel):
    token: str = Field(max_length=128)


def create_app(settings: Settings | None = None, *, app_factory=FastAPI,
               queued_inference: bool = False, embedder=None) -> FastAPI:
    config = settings or Settings.from_env()
    config.prepare()
    database = Database(config.database_path)
    database.fail_interrupted_jobs()
    native_index = SimilarityIndex(config.native_library)
    if config.require_native and native_index.backend != 'cpp':
        raise RuntimeError('The C++ catalog is required. Build the SceneSeek native library before starting.')
    lazy_embedder = embedder or LazyEmbedder(config.embedder, config.clip_model, config.device, config.clip_revision)
    catalog = Catalog(config.index_dir, database, native_index,
                      cache_bytes=config.native_cache_mb * 1024**2, workers=config.native_search_threads)
    service = SceneSeekService(config, database, catalog, lazy_embedder)
    slots = threading.BoundedSemaphore(config.max_pending_jobs)
    searches = threading.BoundedSemaphore(1)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sceneseek")

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=True)

    def index_job(job_id: str, video_id: str):
        try:
            service.index_video(job_id, video_id)
        finally:
            slots.release()

    def owned_video(request: Request, video_id: str):
        try:
            video = database.get_video(video_id)
            if video.get("owner_id") != owner_id(request):
                raise KeyError(video_id)
            return video
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Video not found") from exc

    def public_video(video: dict) -> dict:
        return {key: value for key, value in video.items() if key not in {"media_path", "playback_path", "owner_id"}}

    def guarded_search(function, *args):
        if not searches.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Search is busy. Try again shortly.")
        try:
            return function(*args)
        finally:
            searches.release()

    app = app_factory(
        title="SceneSeek API",
        version=__version__,
        description="Multimodal video retrieval with timestamp and sequence matching.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = config
    app.state.database = database
    app.state.service = service
    app.state.native_index = native_index
    app.state.embedder = lazy_embedder
    dispatches = DispatchRegistry(max_pending=8)

    @app.get("/api/runtime")
    async def runtime(request: Request):
        owner_id(request)
        return {"queued_inference": queued_inference, "temporary": queued_inference,
                "max_video_seconds": config.max_video_seconds,
                "max_upload_mb": config.max_upload_bytes // 1024**2,
                "frame_interval_seconds": config.frame_interval_seconds}

    @app.post("/api/dispatch/cancel", status_code=204, response_class=Response)
    async def cancel_dispatch(request: Request, cancellation: DispatchCancellation):
        dispatches.cancel(cancellation.token, owner_id(request))
        return Response(status_code=204)

    if queued_inference:
        @app.api(name="run_index", concurrency_id="inference", concurrency_limit=1)
        def run_index(token: str) -> dict:
            job_id, video_id = dispatches.claim(token)
            index_job(job_id, video_id)
            return {"id": job_id, "status": database.get_job(job_id)["status"]}

        @app.api(name="run_search", concurrency_id="inference", concurrency_limit=1)
        def run_search(token: str) -> dict:
            mode, query, top_k, owner = dispatches.claim(token)
            started = time.perf_counter()
            try:
                function = {"text": service.text_search, "image": service.image_search, "clip": service.clip_search}[mode]
                results = guarded_search(function, query, top_k, owner)
                return SearchResponse(query_type=mode, results=results,
                                      elapsed_ms=(time.perf_counter()-started)*1000).model_dump()
            finally:
                if mode != "text":
                    query.unlink(missing_ok=True)
    install_security(app, config.data_dir, "SCENESEEK", config.cors_origins, config.max_upload_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        ready = sum(video["status"] == "ready" for video in database.list_videos(owner_id(request)))
        return HealthResponse(
            version=__version__,
            similarity_backend=native_index.backend,
            retrieval_engine=catalog.backend,
            index_storage='ssidx-v1' if catalog.backend == 'cpp' else 'legacy-npz',
            embedder=config.embedder,
            model_loaded=lazy_embedder.loaded,
            indexed_videos=ready,
        )

    @app.get("/api/videos")
    async def list_videos(request: Request) -> list[dict]:
        return [public_video(video) for video in database.list_videos(owner_id(request))]

    @app.post("/api/videos", status_code=202)
    async def upload_video(
        request: Request,
        file: Annotated[UploadFile, File(description="Video to index")],
        title: Annotated[str | None, Query(max_length=120)] = None,
    ) -> dict:
        original_name = file.filename or "video.mp4"
        if queued_inference and len(database.list_videos(owner_id(request))) >= 3:
            await file.close()
            raise HTTPException(status_code=429, detail="Three videos per demo session. Delete a video to add another.")
        extension = Path(original_name).suffix.lower()
        if extension not in VIDEO_EXTENSIONS:
            await file.close()
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported video type. Use: {', '.join(sorted(VIDEO_EXTENSIONS))}",
            )
        if sum(path.stat().st_size for path in config.data_dir.rglob("*") if path.is_file()) >= config.max_storage_bytes:
            raise HTTPException(status_code=507, detail="Storage is full; remove old videos first")
        if not slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="The indexing queue is full. Try again shortly.")
        video_id = uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        destination = config.upload_dir / f"{video_id}{extension}"
        try:
            await _save_upload(file, destination, config.max_upload_bytes)
            video = database.create_video(
                video_id, (title or "").strip() or _safe_display_name(original_name),
                original_name, destination, owner_id(request),
            )
            job = database.create_job(job_id, video_id)
            result = {"video": public_video(video), "job": job}
            if queued_inference:
                def expired():
                    database.update_job(job_id, status="failed", message="Inference could not start", error="The browser queue could not start this request. Upload it again.")
                    database.update_video(video_id, status="failed", error="Inference request expired")
                    slots.release()
                try:
                    token = dispatches.register(owner_id(request), (job_id, video_id), expired)
                except ValueError as exc:
                    database.delete_video(video_id)
                    raise HTTPException(status_code=429, detail=str(exc)) from exc
                result["dispatch"] = {"endpoint": "/run_index", "token": token}
            else:
                executor.submit(index_job, job_id, video_id)
            return result
        except Exception:
            destination.unlink(missing_ok=True)
            slots.release()
            raise

    @app.get("/api/jobs/{job_id}")
    async def get_job(request: Request, job_id: str) -> dict:
        try:
            job = database.get_job(job_id)
            owned_video(request, job["video_id"])
            return job
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.delete("/api/videos/{video_id}", status_code=204, response_class=Response)
    def delete_video(request: Request, video_id: str) -> Response:
        try:
            video = owned_video(request, video_id)
            if video["status"] in {"queued", "processing"}:
                raise HTTPException(status_code=409, detail="Cannot remove a video while indexing")
            service.delete_video(video_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Video not found") from exc
        return Response(status_code=204)

    @app.get("/api/videos/{video_id}/stream")
    def stream_video(request: Request, video_id: str) -> FileResponse:
        try:
            video = owned_video(request, video_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Video not found") from exc
        path = Path(video.get("playback_path") or video["media_path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Video file is missing")
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    @app.get("/api/thumbnails/{video_id}/{filename}")
    def thumbnail(request: Request, video_id: str, filename: str) -> FileResponse:
        owned_video(request, video_id)
        if not re.fullmatch(r"[a-f0-9]{32}", video_id) or not re.fullmatch(
            r"\d{6}\.jpg", filename
        ):
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        path = config.thumbnail_dir / video_id / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/search/text", response_model=SearchResponse)
    def text_search(request: Request, query: TextSearchRequest) -> SearchResponse:
        if queued_inference:
            try:
                token = dispatches.register(owner_id(request), ("text", query.query, query.top_k, owner_id(request)))
            except ValueError as exc:
                raise HTTPException(status_code=429, detail=str(exc)) from exc
            return JSONResponse({"dispatch": {"endpoint": "/run_search", "token": token}})
        started = time.perf_counter()
        try:
            results = guarded_search(service.text_search, query.query, query.top_k, owner_id(request))
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return SearchResponse(
            query_type="text",
            elapsed_ms=(time.perf_counter() - started) * 1000,
            results=results,
        )

    async def file_search(
        upload: UploadFile,
        query_type: str,
        top_k: int,
        extensions: set[str],
        owner: str,
    ) -> SearchResponse:
        extension = Path(upload.filename or "").suffix.lower()
        if extension not in extensions:
            raise HTTPException(status_code=415, detail="Unsupported query file type")
        path = config.temp_dir / f"{uuid.uuid4().hex}{extension}"
        await _save_upload(upload, path, config.max_query_bytes)
        if queued_inference:
            try:
                token = dispatches.register(owner, (query_type, path, top_k, owner), lambda: path.unlink(missing_ok=True))
            except ValueError as exc:
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=429, detail=str(exc)) from exc
            return JSONResponse({"dispatch": {"endpoint": "/run_search", "token": token}})
        started = time.perf_counter()
        try:
            if query_type == "image":
                results = await run_in_threadpool(guarded_search, service.image_search, path, top_k, owner)
            else:
                results = await run_in_threadpool(guarded_search, service.clip_search, path, top_k, owner)
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            path.unlink(missing_ok=True)
        return SearchResponse(
            query_type=query_type,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            results=results,
        )

    @app.post("/api/search/image", response_model=SearchResponse)
    async def image_search(
        request: Request,
        file: Annotated[UploadFile, File()],
        top_k: Annotated[int, Query(ge=1, le=50)] = 12,
    ) -> SearchResponse:
        return await file_search(file, "image", top_k, IMAGE_EXTENSIONS, owner_id(request))

    @app.post("/api/search/clip", response_model=SearchResponse)
    async def clip_search(
        request: Request,
        file: Annotated[UploadFile, File()],
        top_k: Annotated[int, Query(ge=1, le=50)] = 12,
    ) -> SearchResponse:
        return await file_search(file, "clip", top_k, VIDEO_EXTENSIONS, owner_id(request))

    if config.frontend_dir and (config.frontend_dir / "index.html").is_file():
        assets = config.frontend_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/" if queued_inference else "/{requested_path:path}", include_in_schema=False)
        def frontend(requested_path: str = "") -> FileResponse:
            if requested_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Endpoint not found")
            candidate = (config.frontend_dir / requested_path).resolve()
            if (
                requested_path
                and candidate.is_file()
                and config.frontend_dir in candidate.parents
            ):
                return FileResponse(candidate)
            return FileResponse(config.frontend_dir / "index.html")

    return app


app = create_app()
