from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from fastapi import Request
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from .config import get_settings
from .database import Base, SessionLocal, engine
from .routers import access, admin, auth, compatibility, gate, requests, user
from .security import LoginRateLimiter
from .services.auth import ensure_admin_user, ensure_bootstrap_test_users, ensure_demo_user
from .services.gate_event_worker import courier_gate_event_worker
from .services.requests import (
    cleanup_broken_requests,
    cleanup_duplicate_requests,
    cleanup_expired_requests,
    ensure_admin_permanent_request,
    ensure_active_request_unique_index,
    ensure_requests_schema,
)
from .services.user_accounts import ensure_users_schema

settings = get_settings()
logging.basicConfig(level=logging.INFO)
_FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _split_host_and_port(raw_host: str | None) -> str:
    if not raw_host:
        return ""

    host = raw_host.split(",", 1)[0].strip().rstrip(".")
    if host.startswith("["):
        closing_bracket = host.find("]")
        if closing_bracket != -1:
            return host[1:closing_bracket].lower()
    if host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host.lower()


def _host_aliases(host: str) -> set[str]:
    normalized = host.strip().rstrip(".").lower()
    aliases = {normalized}

    try:
        aliases.add(normalized.encode("idna").decode("ascii").lower())
    except UnicodeError:
        pass

    try:
        aliases.add(normalized.encode("ascii").decode("idna").lower().rstrip("."))
    except UnicodeError:
        pass

    return {alias for alias in aliases if alias}


@lru_cache
def _compiled_allowed_hosts() -> tuple[bool, tuple[tuple[set[str], bool], ...]]:
    if "*" in settings.allowed_hosts:
        return True, ()

    compiled_patterns: list[tuple[set[str], bool]] = []
    for raw_pattern in settings.allowed_hosts:
        is_subdomain_pattern = raw_pattern.startswith("*.")
        base_pattern = raw_pattern[2:] if is_subdomain_pattern else raw_pattern
        compiled_patterns.append((_host_aliases(base_pattern), is_subdomain_pattern))

    return False, tuple(compiled_patterns)


def _is_allowed_host(raw_host: str | None) -> bool:
    host = _split_host_and_port(raw_host)
    if not host:
        return False

    allow_all, compiled_patterns = _compiled_allowed_hosts()
    if allow_all:
        return True

    host_candidates = _host_aliases(host)
    for allowed_candidates, is_subdomain_pattern in compiled_patterns:
        if host_candidates & allowed_candidates:
            return True
        if is_subdomain_pattern:
            for candidate in host_candidates:
                if any(candidate.endswith(f".{allowed}") for allowed in allowed_candidates):
                    return True
    return False

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.login_rate_limiter = LoginRateLimiter(
    attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    if not _is_allowed_host(request.headers.get("host")):
        return PlainTextResponse("Invalid host header", status_code=400)

    response = await call_next(request)
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.on_event("startup")
async def startup_event() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        await ensure_users_schema(session)
        await ensure_requests_schema(session)
        broken_count = await cleanup_broken_requests(session)
        if broken_count:
            logging.info("Cleaned up %s broken active requests with invalid gate_key_id", broken_count)
        duplicate_count = await cleanup_duplicate_requests(session)
        if duplicate_count:
            logging.info("Cleaned up %s duplicate active requests", duplicate_count)
        expired_count = await cleanup_expired_requests(session, remove_gate_keys=False)
        if expired_count:
            logging.info("Marked %s expired active requests as expired", expired_count)
        await ensure_active_request_unique_index(session)
        await ensure_demo_user(session)
        await ensure_admin_user(session)
        try:
            admin_request = await ensure_admin_permanent_request(session)
            if admin_request is not None:
                logging.info("Ensured admin permanent Gate request id=%s", admin_request.id)
        except Exception:
            logging.exception("Failed to ensure admin permanent Gate request")
        await ensure_bootstrap_test_users(session)

    if settings.gate_real_integration_enabled and settings.gate_event_poll_enabled:
        existing_task = getattr(app.state, "courier_gate_event_task", None)
        if existing_task is None or existing_task.done():
            app.state.courier_gate_event_task = asyncio.create_task(courier_gate_event_worker())
            logging.info("Started Gate exit event courier worker")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    task = getattr(app.state, "courier_gate_event_task", None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(access.router, prefix=settings.api_prefix)
app.include_router(access.legacy_router, prefix=settings.api_prefix)
app.include_router(gate.router, prefix=settings.api_prefix)
app.include_router(requests.router, prefix=settings.api_prefix)
app.include_router(user.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(compatibility.router)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


def _resolve_frontend_path(relative_path: str) -> Path:
    requested_path = (relative_path or "").strip().replace("\\", "/").strip("/")
    target_path = (_FRONTEND_DIST_DIR / requested_path).resolve()

    if target_path != _FRONTEND_DIST_DIR and _FRONTEND_DIST_DIR not in target_path.parents:
        raise HTTPException(status_code=404)

    return target_path


def _serve_frontend_asset(relative_path: str) -> FileResponse:
    if not _FRONTEND_DIST_DIR.is_dir():
        raise HTTPException(status_code=404)

    index_path = _FRONTEND_DIST_DIR / "index.html"
    requested_path = _resolve_frontend_path(relative_path)

    if requested_path.is_file():
        response = FileResponse(requested_path)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    nested_index = requested_path / "index.html"
    if nested_index.is_file():
        response = FileResponse(nested_index)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    if index_path.is_file():
        response = FileResponse(index_path)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    raise HTTPException(status_code=404)


@app.get("/")
async def frontend_index() -> FileResponse:
    return _serve_frontend_asset("")


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
async def frontend_spa(full_path: str) -> FileResponse:
    return _serve_frontend_asset(full_path)
