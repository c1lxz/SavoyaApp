from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import time
import warnings
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import anyio
from fastapi import HTTPException, Request
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response, StreamingResponse
from starlette.formparsers import MultiPartException

from ..config import get_settings
from ..news_models import NewsMedia, utcnow

settings = get_settings()
_ID = re.compile(r"^[0-9a-f]{32}$")
Image.MAX_IMAGE_PIXELS = 40_000_000


class UploadTooLarge(MultiPartException):
    def __init__(self):
        # Starlette catches this base class and closes all partially spooled files.
        super().__init__("news_upload_too_large")


class NewsUploadLimitMiddleware:
    """Bound multipart bytes before Starlette spools the entire upload to disk."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path", "").rstrip("/") != f"{settings.api_prefix}/news/media":
            return await self.app(scope, receive, send)
        limit = settings.news_max_upload_bytes + 64 * 1024
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = 0
        if length > limit:
            return await Response('Файл слишком большой', status_code=413)(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise UploadTooLarge()
            return message

        await self.app(scope, bounded_receive, send)


def media_path(media_id: str, thumbnail: bool = False) -> Path:
    if not _ID.fullmatch(media_id):
        raise HTTPException(404, "Файл не найден")
    root = Path(settings.news_media_dir).resolve()
    path = root / (f"{media_id}.thumb.jpg" if thumbnail else f"{media_id}.blob")
    if path.is_symlink() or path.resolve().parent != root:
        raise HTTPException(404, "Файл не найден")
    return path


def safe_filename(name: str | None) -> str:
    name = (name or "Файл").replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r'[\x00-\x1f\x7f<>:"|?*]', "_", name).strip(" .")[:240] or "Файл"


def _signature(media_id: str, variant: str, expires: int) -> str:
    payload = f"news-media:{media_id}:{variant}:{expires}".encode()
    return hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).hexdigest()


def signed_url(media_id: str, thumbnail: bool = False) -> str:
    variant = "thumbnail" if thumbnail else "content"
    expires = int(time.time()) + settings.news_media_url_ttl_seconds
    return f"{settings.api_prefix}/news/media/{media_id}/{variant}?expires={expires}&signature={_signature(media_id, variant, expires)}"


def verify_signature(media_id: str, variant: str, expires: int, signature: str):
    if expires < int(time.time()) or expires > int(time.time()) + settings.news_media_url_ttl_seconds + 60:
        raise HTTPException(403, "Ссылка устарела. Обновите новости")
    if not hmac.compare_digest(_signature(media_id, variant, expires), signature):
        raise HTTPException(403, "Недействительная ссылка")


def serialize_media(item: NewsMedia) -> dict:
    return {
        "id": item.id, "name": item.name, "mime_type": item.mime_type,
        "size_bytes": item.size_bytes, "kind": item.kind,
        "url": signed_url(item.id),
        "thumbnail_url": signed_url(item.id, True) if item.has_thumbnail else None,
    }


def inspect_media(path: Path, name: str) -> tuple[str, str, bool]:
    """Only decoded images / recognized video containers are rendered inline."""
    suffix = Path(name).suffix.lower()
    with path.open("rb") as source:
        header = source.read(32)
    looks_image = header.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n", b"GIF87a", b"GIF89a")) or header[8:12] == b"WEBP"
    if looks_image or suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as original:
                    image_format = original.format
                    if image_format not in {"JPEG", "PNG", "GIF", "WEBP"}:
                        raise ValueError("Unsupported image")
                    original.verify()
                with Image.open(path) as original:
                    original.seek(0)
                    thumbnail = ImageOps.exif_transpose(original)
                    thumbnail.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                    if thumbnail.mode != "RGB":
                        canvas = Image.new("RGB", thumbnail.size, "white")
                        if "A" in thumbnail.getbands():
                            canvas.paste(thumbnail, mask=thumbnail.getchannel("A"))
                        else:
                            canvas.paste(thumbnail.convert("RGB"))
                        thumbnail = canvas
                    thumbnail.save(path.with_suffix(".thumb.jpg"), "JPEG", quality=82, optimize=True)
            return "image", Image.MIME[image_format], True
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise HTTPException(422, "Не удалось прочитать фотографию. Выберите исправный JPG, PNG, GIF или WebP") from exc
    if suffix in {".mp4", ".m4v", ".mov"} and header[4:8] == b"ftyp":
        return "video", "video/quicktime" if suffix == ".mov" else "video/mp4", False
    if suffix == ".webm" and header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", "video/webm", False
    return "document", "application/octet-stream", False


async def delete_files(media_id: str):
    for thumbnail in (False, True):
        path = media_path(media_id, thumbnail)
        await asyncio.to_thread(path.unlink, missing_ok=True)


async def cleanup_unattached(session: AsyncSession) -> int:
    cutoff = utcnow() - timedelta(hours=settings.news_unattached_ttl_hours)
    rows = list((await session.scalars(select(NewsMedia).where(
        NewsMedia.post_id.is_(None), NewsMedia.detached_at < cutoff,
    ).limit(100))).all())
    removed = 0
    for item in rows:
        # Conditional deletion prevents a concurrent publication from losing its file.
        result = await session.execute(delete(NewsMedia).where(
            NewsMedia.id == item.id, NewsMedia.post_id.is_(None), NewsMedia.detached_at < cutoff,
        ).execution_options(synchronize_session=False))
        if result.rowcount:
            await session.commit()
            await delete_files(item.id)
            removed += 1
    return removed


async def file_response(request: Request, item: NewsMedia, thumbnail: bool):
    path = media_path(item.id, thumbnail)
    if not path.is_file():
        raise HTTPException(404, "Файл не найден")
    size = path.stat().st_size
    mime = "image/jpeg" if thumbnail else item.mime_type
    inline = thumbnail or item.kind in {"image", "video"}
    disposition = "inline" if inline else "attachment"
    filename = f"{item.id}.jpg" if thumbnail else item.name
    headers = {
        "Accept-Ranges": "bytes", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, no-store",
        "Content-Disposition": f"{disposition}; filename=\"download\"; filename*=UTF-8''{quote(filename, safe='')}",
    }
    start, end, status_code = 0, size - 1, 200
    requested_range = request.headers.get("range")
    if requested_range:
        match = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", requested_range.strip())
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        left, right = match.groups()
        if left:
            start = int(left)
            end = min(int(right), size - 1) if right else size - 1
        else:
            start = max(0, size - int(right))
        if start > end or start >= size or (not left and int(right) == 0):
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1
    headers["Content-Length"] = str(length)
    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers, media_type=mime)

    async def chunks():
        remaining = length
        async with await anyio.open_file(path, "rb") as source:
            await source.seek(start)
            while remaining:
                chunk = await source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(chunks(), status_code=status_code, headers=headers, media_type=mime)
