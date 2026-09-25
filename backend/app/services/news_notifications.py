"""Durable, leased FCM outbox. FCM acceptance is not device delivery confirmation."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from uuid import uuid4

import httpx
from sqlalchemy import select, update

from ..config import get_settings
from ..database import SessionLocal
from ..models import User
from ..news_models import NewsDevice, NewsNotification, NewsPost, utcnow
from .news_media import cleanup_unattached
from ..utils.datetime import ensure_utc_datetime

settings = get_settings()
logger = logging.getLogger(__name__)


class PushFailure(Exception):
    def __init__(self, code: str, *, invalid_token: bool = False, permanent: bool = False):
        self.code, self.invalid_token, self.permanent = code, invalid_token, permanent
        super().__init__(code)


class FcmSender:
    def __init__(self):
        self.credentials = None
        self.lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(settings.news_fcm_service_account_file)

    async def send(self, token: str, post: NewsPost):
        if not self.configured:
            raise PushFailure("fcm_not_configured")
        async with self.lock:
            try:
                if self.credentials is None:
                    from google.oauth2.service_account import Credentials
                    self.credentials = Credentials.from_service_account_file(
                        settings.news_fcm_service_account_file,
                        scopes=["https://www.googleapis.com/auth/firebase.messaging"],
                    )
                if not self.credentials.valid:
                    from google.auth.transport.requests import Request
                    await asyncio.to_thread(self.credentials.refresh, Request())
                access_token = self.credentials.token
                project_id = settings.news_fcm_project_id or self.credentials.project_id
            except Exception as exc:
                # Never put the service-account contents, token, or provider response in logs.
                raise PushFailure("fcm_credentials_unavailable") from exc
        message = {
            "token": token,
            "notification": {"title": "Новости Савоя", "body": "Опубликована новая новость. Откройте приложение, чтобы прочитать"},
            "data": {"screen": "news", "news_id": str(post.id)},
            "android": {
                "priority": "high", "ttl": "86400s", "collapse_key": f"news-{post.id}",
                "notification": {"channel_id": "news", "tag": f"news-{post.id}", "sound": "default"},
            },
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
                    headers={"Authorization": f"Bearer {access_token}"}, json={"message": message},
                )
        except httpx.HTTPError as exc:
            raise PushFailure("fcm_transport_unknown") from exc
        if response.is_success:
            return
        error_code = ""
        try:
            details = response.json().get("error", {}).get("details", [])
            for detail in details:
                if detail.get("@type", "").endswith("google.firebase.fcm.v1.FcmError"):
                    error_code = detail.get("errorCode", "")
        except (ValueError, TypeError, AttributeError):
            pass
        if error_code == "UNREGISTERED":
            raise PushFailure("fcm_unregistered", invalid_token=True, permanent=True)
        if error_code == "SENDER_ID_MISMATCH":
            raise PushFailure("fcm_sender_mismatch", permanent=True)
        raise PushFailure(f"fcm_http_{response.status_code}", permanent=response.status_code == 400)


async def process_outbox_once(sender=None, session_factory=SessionLocal, batch_size: int = 30) -> int:
    sender = sender or FcmSender()
    if not sender.configured:
        return 0  # Pending remains pending. Missing credentials never count as delivery.
    now = utcnow()
    async with session_factory() as session:
        ids = list((await session.scalars(select(NewsNotification.id).where(
            NewsNotification.status.in_(["pending", "retry", "sending"]), NewsNotification.next_attempt_at <= now,
        ).order_by(NewsNotification.id).limit(batch_size))).all())
    completed = 0
    for notification_id in ids:
        lease_id = uuid4().hex
        async with session_factory() as session:
            claim = await session.execute(update(NewsNotification).where(
                NewsNotification.id == notification_id,
                NewsNotification.status.in_(["pending", "retry", "sending"]),
                NewsNotification.next_attempt_at <= utcnow(),
            ).values(status="sending", lease_id=lease_id, next_attempt_at=utcnow() + timedelta(minutes=5),
                     attempts=NewsNotification.attempts + 1))
            await session.commit()
            if not claim.rowcount:
                continue
            notification = await session.get(NewsNotification, notification_id)
            post = await session.get(NewsPost, notification.post_id)
            device = await session.get(NewsDevice, notification.device_id)
            user = await session.get(User, device.user_id) if device else None
            stale_device = device and ensure_utc_datetime(device.updated_at) < utcnow() - timedelta(days=settings.news_device_ttl_days)
            stale_post = post and ensure_utc_datetime(post.created_at) < utcnow() - timedelta(days=1)
            if not post or post.deleted_at or stale_post or not device or not device.active or stale_device or not user or not user.is_active:
                await session.execute(update(NewsNotification).where(
                    NewsNotification.id == notification_id, NewsNotification.lease_id == lease_id,
                ).values(status="cancelled", lease_id=None))
                await session.commit()
                continue
            # Do not hold a DB transaction while requesting Google.
            token, attempts = device.token, notification.attempts
            await session.commit()
            try:
                await sender.send(token, post)
                values = {"status": "sent", "sent_at": utcnow(), "last_error": None, "lease_id": None}
            except PushFailure as exc:
                values = {
                    "status": "failed" if exc.permanent or attempts >= 12 else "retry",
                    "last_error": exc.code, "lease_id": None,
                    "next_attempt_at": utcnow() + timedelta(seconds=min(21600, 30 * 2 ** min(attempts, 10))),
                }
                if exc.invalid_token:
                    await session.execute(update(NewsDevice).where(NewsDevice.id == device.id, NewsDevice.token == token).values(active=False))
            except Exception:
                values = {"status": "retry", "last_error": "worker_error", "lease_id": None,
                          "next_attempt_at": utcnow() + timedelta(minutes=5)}
                logger.warning("News push worker failed for outbox row %s", notification_id)
            await session.execute(update(NewsNotification).where(
                NewsNotification.id == notification_id, NewsNotification.lease_id == lease_id,
            ).values(**values))
            await session.commit()
            completed += 1
    return completed


async def news_worker():
    sender = FcmSender()
    if not sender.configured:
        logger.warning("News push is not configured: publications are saved, push outbox remains pending")
    last_cleanup = 0.0
    while True:
        try:
            await process_outbox_once(sender)
            if time.monotonic() - last_cleanup >= 3600:
                async with SessionLocal() as session:
                    await cleanup_unattached(session)
                last_cleanup = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("News background maintenance failed")
        await asyncio.sleep(10)
