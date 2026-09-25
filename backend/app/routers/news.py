from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta
from typing import Literal
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import get_settings
from ..database import get_db_session
from ..dependencies import get_current_admin_user, get_current_user
from ..models import User
from ..news_models import NewsDevice, NewsMedia, NewsNotification, NewsPost, utcnow
from ..services.news_media import (
    UploadTooLarge, delete_files, file_response, inspect_media, media_path,
    safe_filename, serialize_media, verify_signature,
)
from ..utils.datetime import ensure_utc_datetime

router = APIRouter(prefix="/news", tags=["news"])
settings = get_settings()


class PostBody(BaseModel):
    text: str = Field(default="", max_length=20000)
    media_ids: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("text")
    @classmethod
    def trim_text(cls, value):
        return value.strip()

    @field_validator("media_ids")
    @classmethod
    def validate_ids(cls, values):
        if len(set(values)) != len(values) or any(len(v) != 32 or any(c not in "0123456789abcdef" for c in v) for v in values):
            raise ValueError("Некорректные вложения")
        return values

    @model_validator(mode="after")
    def nonempty(self):
        if not self.text and not self.media_ids:
            raise ValueError("Добавьте текст или вложение")
        return self


class CreatePostBody(PostBody):
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class UpdatePostBody(PostBody):
    version: int = Field(ge=1)


class DeviceBody(BaseModel):
    # FCM registration tokens are ASCII; bound indexed bytes for PostgreSQL too.
    token: str = Field(min_length=10, max_length=2048, pattern=r"^[A-Za-z0-9_:.\-]+$")
    platform: Literal["android", "ios"] = "android"


async def serialize_posts(session: AsyncSession, posts: list[NewsPost]) -> list[dict]:
    if not posts:
        return []
    media = (await session.scalars(select(NewsMedia).where(
        NewsMedia.post_id.in_([post.id for post in posts]),
    ).order_by(NewsMedia.position))).all()
    by_post: dict[int, list] = {}
    for item in media:
        by_post.setdefault(item.post_id, []).append(serialize_media(item))
    return [{
        "id": post.id, "text": post.text, "media": by_post.get(post.id, []),
        "author_name": post.author_name, "version": post.version,
        "created_at": ensure_utc_datetime(post.created_at),
        "updated_at": ensure_utc_datetime(post.updated_at),
    } for post in posts]


async def get_post(session: AsyncSession, post_id: int) -> NewsPost:
    post = await session.get(NewsPost, post_id)
    if post is None or post.deleted_at is not None:
        raise HTTPException(404, "Новость не найдена")
    return post


@router.get("")
async def list_news(
    limit: int = Query(1, ge=1, le=20), before_id: int | None = Query(None, ge=1),
    session: AsyncSession = Depends(get_db_session), _user: User = Depends(get_current_user),
):
    query = select(NewsPost).where(NewsPost.deleted_at.is_(None))
    if before_id is not None:
        query = query.where(NewsPost.id < before_id)
    rows = list((await session.scalars(query.order_by(NewsPost.id.desc()).limit(limit + 1))).all())
    visible = rows[:limit]
    return {"items": await serialize_posts(session, visible), "next_cursor": visible[-1].id if len(rows) > limit else None}


@router.post("/media", status_code=201)
async def upload_media(
    request: Request, session: AsyncSession = Depends(get_db_session), admin: User = Depends(get_current_admin_user),
):
    count = await session.scalar(select(func.count()).select_from(NewsMedia).where(
        NewsMedia.owner_id == admin.id, NewsMedia.post_id.is_(None), NewsMedia.available.is_(True),
        NewsMedia.detached_at >= utcnow() - timedelta(hours=settings.news_unattached_ttl_hours),
    ))
    if count >= settings.news_max_unattached_uploads:
        raise HTTPException(429, "Слишком много незавершённых загрузок. Удалите лишние вложения")
    media_id = uuid4().hex
    path = media_path(media_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    committed = False
    try:
        # Parse only after authentication and quota checks; total body is bounded by middleware.
        async with request.form(max_files=1, max_fields=0) as form:
            file = form.get("file")
            if not isinstance(file, UploadFile) or len(form) != 1:
                raise HTTPException(422, "Выберите один файл")
            name = safe_filename(file.filename)
            total = 0
            async with await anyio.open_file(path, "xb") as target:
                while chunk := await file.read(64 * 1024):
                    total += len(chunk)
                    if total > settings.news_max_upload_bytes:
                        raise HTTPException(413, "Файл больше допустимого размера")
                    await target.write(chunk)
            if not total:
                raise HTTPException(422, "Пустой файл")
        kind, mime_type, has_thumbnail = await asyncio.to_thread(inspect_media, path, name)
        item = NewsMedia(id=media_id, owner_id=admin.id, name=name, size_bytes=total,
                         kind=kind, mime_type=mime_type, has_thumbnail=has_thumbnail)
        session.add(item)
        await session.commit()
        committed = True
        return serialize_media(item)
    except UploadTooLarge as exc:
        raise HTTPException(413, "Файл больше допустимого размера") from exc
    except StarletteHTTPException as exc:
        if exc.status_code == 400 and exc.detail == "news_upload_too_large":
            raise HTTPException(413, "Файл больше допустимого размера") from exc
        raise
    finally:
        if not committed:
            await delete_files(media_id)


@router.delete("/media/{media_id}", status_code=204)
async def discard_media(
    media_id: str, session: AsyncSession = Depends(get_db_session), admin: User = Depends(get_current_admin_user),
):
    media_path(media_id)
    removed = await session.execute(delete(NewsMedia).where(
        NewsMedia.id == media_id, NewsMedia.owner_id == admin.id, NewsMedia.post_id.is_(None),
    ))
    if not removed.rowcount:
        raise HTTPException(404, "Свободное вложение не найдено")
    await session.commit()
    await delete_files(media_id)
    return Response(status_code=204)


@router.get("/media/{media_id}")
async def refresh_media_metadata(
    media_id: str, session: AsyncSession = Depends(get_db_session), admin: User = Depends(get_current_admin_user),
):
    media_path(media_id)
    cutoff = utcnow() - timedelta(hours=settings.news_unattached_ttl_hours)
    item = await session.scalar(select(NewsMedia).where(
        NewsMedia.id == media_id, NewsMedia.available.is_(True),
        ((NewsMedia.owner_id == admin.id) & NewsMedia.post_id.is_(None) & (NewsMedia.detached_at >= cutoff))
        | NewsMedia.post_id.is_not(None),
    ))
    if item is None:
        raise HTTPException(404, "Вложение устарело. Выберите файл заново")
    if item.post_id is not None:
        await get_post(session, item.post_id)
    return serialize_media(item)


@router.api_route("/media/{media_id}/{variant}", methods=["GET", "HEAD"])
async def download_media(
    request: Request, media_id: str, variant: Literal["content", "thumbnail"],
    expires: int, signature: str = Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
    session: AsyncSession = Depends(get_db_session),
):
    media_path(media_id)
    verify_signature(media_id, variant, expires, signature)
    item = await session.get(NewsMedia, media_id)
    if item is None or not item.available or (variant == "thumbnail" and not item.has_thumbnail):
        raise HTTPException(404, "Файл не найден")
    if item.post_id is not None:
        await get_post(session, item.post_id)
    return await file_response(request, item, variant == "thumbnail")


@router.post("/devices", status_code=204)
async def register_device(
    body: DeviceBody, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user),
):
    device = await session.scalar(select(NewsDevice).where(NewsDevice.token == body.token).with_for_update())
    if device is None:
        device = NewsDevice(token=body.token, user_id=user.id, platform=body.platform)
        session.add(device)
    else:
        if device.user_id != user.id:
            await session.execute(update(NewsNotification).where(
                NewsNotification.device_id == device.id, NewsNotification.status.in_(["pending", "retry", "sending"]),
            ).values(status="cancelled", lease_id=None))
        device.user_id, device.platform, device.active, device.updated_at = user.id, body.platform, True, utcnow()
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Регистрация уже выполняется. Повторите запрос")
    return Response(status_code=204)


@router.delete("/devices", status_code=204)
async def unregister_device(
    body: DeviceBody, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user),
):
    device = await session.scalar(select(NewsDevice).where(NewsDevice.token == body.token, NewsDevice.user_id == user.id))
    if device:
        device.active = False
        await session.execute(update(NewsNotification).where(
            NewsNotification.device_id == device.id, NewsNotification.status.in_(["pending", "retry", "sending"]),
        ).values(status="cancelled", lease_id=None))
        await session.commit()
    return Response(status_code=204)


def fingerprint(body: PostBody) -> str:
    return hashlib.sha256(json.dumps({"text": body.text, "media_ids": body.media_ids}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def replay(session: AsyncSession, post: NewsPost, digest: str):
    if post.request_hash != digest:
        raise HTTPException(409, "Этот идентификатор публикации уже использован с другим содержимым")
    if post.deleted_at:
        raise HTTPException(410, "Эта публикация уже удалена")
    return (await serialize_posts(session, [post]))[0]


async def attach_media(session: AsyncSession, ids: list[str], post_id: int, admin_id: int):
    cutoff = utcnow() - timedelta(hours=settings.news_unattached_ttl_hours)
    for position, media_id in enumerate(ids):
        result = await session.execute(update(NewsMedia).where(
            NewsMedia.id == media_id,
            ((NewsMedia.owner_id == admin_id) & NewsMedia.post_id.is_(None)
             & NewsMedia.available.is_(True) & (NewsMedia.detached_at >= cutoff)) | (NewsMedia.post_id == post_id),
        ).values(post_id=post_id, position=position, detached_at=None, available=True))
        if result.rowcount != 1:
            await session.rollback()
            raise HTTPException(409, "Вложение недоступно. Загрузите его заново")


@router.post("", status_code=201)
async def create_news(
    body: CreatePostBody, session: AsyncSession = Depends(get_db_session), admin: User = Depends(get_current_admin_user),
):
    digest = fingerprint(body)
    admin_id = admin.id
    existing = await session.scalar(select(NewsPost).where(NewsPost.author_id == admin_id, NewsPost.request_id == body.request_id))
    if existing:
        return await replay(session, existing, digest)
    post = NewsPost(author_id=admin_id, author_name=admin.name or "Председатель", text=body.text,
                    request_id=body.request_id, request_hash=digest)
    session.add(post)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(select(NewsPost).where(NewsPost.author_id == admin_id, NewsPost.request_id == body.request_id))
        if existing:
            return await replay(session, existing, digest)
        raise
    await attach_media(session, body.media_ids, post.id, admin_id)
    device_ids = (await session.scalars(select(NewsDevice.id).join(User, NewsDevice.user_id == User.id).where(
        NewsDevice.active.is_(True), User.is_active.is_(True),
        NewsDevice.updated_at >= utcnow() - timedelta(days=settings.news_device_ttl_days),
    ))).all()
    session.add_all([NewsNotification(post_id=post.id, device_id=device_id) for device_id in device_ids])
    await session.commit()
    return (await serialize_posts(session, [post]))[0]


@router.get("/{post_id}")
async def read_news(post_id: int, session: AsyncSession = Depends(get_db_session), _user: User = Depends(get_current_user)):
    return (await serialize_posts(session, [await get_post(session, post_id)]))[0]


@router.put("/{post_id}")
async def edit_news(
    post_id: int, body: UpdatePostBody, session: AsyncSession = Depends(get_db_session), admin: User = Depends(get_current_admin_user),
):
    await get_post(session, post_id)
    changed = await session.execute(update(NewsPost).where(
        NewsPost.id == post_id, NewsPost.deleted_at.is_(None), NewsPost.version == body.version,
    ).values(text=body.text, version=NewsPost.version + 1, updated_at=utcnow()))
    if changed.rowcount != 1:
        raise HTTPException(409, "Новость уже изменена. Обновите её перед редактированием")
    await attach_media(session, body.media_ids, post_id, admin.id)
    await session.execute(update(NewsMedia).where(
        NewsMedia.post_id == post_id, NewsMedia.id.not_in(body.media_ids),
    ).values(post_id=None, detached_at=utcnow(), available=False))
    await session.commit()
    post = await get_post(session, post_id)
    await session.refresh(post)
    return (await serialize_posts(session, [post]))[0]


@router.delete("/{post_id}", status_code=204)
async def delete_news(
    post_id: int, version: int = Query(ge=1), session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(get_current_admin_user),
):
    await get_post(session, post_id)
    removed = await session.execute(update(NewsPost).where(
        NewsPost.id == post_id, NewsPost.deleted_at.is_(None), NewsPost.version == version,
    ).values(deleted_at=utcnow(), version=NewsPost.version + 1))
    if removed.rowcount != 1:
        raise HTTPException(409, "Новость уже изменена. Обновите её перед удалением")
    await session.execute(update(NewsMedia).where(NewsMedia.post_id == post_id).values(post_id=None, detached_at=utcnow(), available=False))
    await session.execute(update(NewsNotification).where(
        NewsNotification.post_id == post_id, NewsNotification.status.in_(["pending", "retry", "sending"]),
    ).values(status="cancelled", lease_id=None))
    await session.commit()
    return Response(status_code=204)
