from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from ..config import get_settings

settings = get_settings()


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    ttl = expires_minutes or settings.access_token_expire_minutes
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=ttl)
    payload = {
        "sub": subject,
        "exp": expires_at,
        "iat": issued_at,
        "nbf": issued_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except JWTError as exc:
        raise ValueError("Invalid token") from exc

