"""Browser-session isolation and safe defaults for the single-process app."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse


def owner_id(request: Request) -> str:
    return request.session.setdefault("owner", secrets.token_hex(24))


def install_security(app: FastAPI, data_dir: Path, prefix: str, origins: tuple[str, ...], max_body: int) -> None:
    secret = os.getenv(f"{prefix}_SESSION_SECRET", "").strip()
    if not secret:
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / ".session-secret"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            secret = path.read_text().strip()
        else:
            secret = secrets.token_hex(32)
            with os.fdopen(descriptor, "w") as handle:
                handle.write(secret)
    if len(secret) < 32:
        raise ValueError(f"{prefix}_SESSION_SECRET must contain at least 32 characters")
    app.add_middleware(
        SessionMiddleware, secret_key=secret, session_cookie=prefix.lower() + "_session",
        max_age=7 * 24 * 3600, same_site="lax",
        https_only=os.getenv(f"{prefix}_COOKIE_SECURE", "false").lower() == "true",
    )

    @app.middleware("http")
    async def browser_security(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            own_origin = f"{request.url.scheme}://{request.url.netloc}"
            if origin and origin not in {*origins, own_origin, f"https://{request.url.netloc}"}:
                return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
            length = request.headers.get("content-length")
            if request.method in {"POST", "PUT"} and length is None:
                return JSONResponse({"detail": "Content-Length is required"}, status_code=411)
            if length:
                try:
                    oversized = int(length) < 0 or int(length) > max_body + 1024 * 1024
                except ValueError:
                    return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
                if oversized:
                    return JSONResponse({"detail": "Request is too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if request.url.path == "/api/docs":
            # FastAPI's Swagger shell uses a CDN and an inline initializer.
            # Keep this exception confined to the documentation document.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; object-src 'none'; frame-ancestors 'none'"
            )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

