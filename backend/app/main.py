from __future__ import annotations

import logging

from fastapi import Request
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .config import get_settings
from .database import Base, SessionLocal, engine
from .routers import access, auth, compatibility, gate, requests, user
from .security import LoginRateLimiter
from .services.auth import ensure_demo_user

settings = get_settings()
logging.basicConfig(level=logging.INFO)

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
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.state.login_rate_limiter = LoginRateLimiter(
    attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
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
        await ensure_demo_user(session)


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(access.router, prefix=settings.api_prefix)
app.include_router(access.legacy_router, prefix=settings.api_prefix)
app.include_router(gate.router, prefix=settings.api_prefix)
app.include_router(requests.router, prefix=settings.api_prefix)
app.include_router(user.router, prefix=settings.api_prefix)
app.include_router(compatibility.router)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
