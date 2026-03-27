from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from ..config import get_settings

settings = get_settings()


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    ttl = expires_minutes or settings.access_token_expire_minutes
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc

