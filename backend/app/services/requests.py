from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Request, User
from ..schemas import CreateRequestRequest
from .gate import gate_client

settings = get_settings()


def resolve_request_status(is_permanent: bool, expires_at: datetime | None) -> str:
    if is_permanent:
        return "permanent"
    if expires_at and expires_at < datetime.now(timezone.utc):
        return "expired"
    return "active"


async def create_request(session: AsyncSession, user: User, payload: CreateRequestRequest) -> Request:
    is_permanent = payload.is_permanent
    request_hours = payload.hours

    if payload.is_courier and settings.courier_ttl_only_enabled:
        is_permanent = False
        base_hours = request_hours if request_hours is not None else settings.courier_default_hours
        request_hours = min(base_hours, settings.courier_max_hours)

    expires_at: datetime | None = None
    if not is_permanent:
        hours = request_hours if request_hours is not None else 24
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)

    if is_permanent:
        gate_key_id = gate_client.add_permanent_key(
            key_type=payload.key_type,
            key_value=payload.key_value,
            access_point_ids=payload.access_point_ids,
            resident_name=user.name or user.login or "Resident",
        )
    else:
        gate_key_id = gate_client.add_temporary_key(
            key_type=payload.key_type,
            key_value=payload.key_value,
            expires_at=expires_at,
            access_point_ids=payload.access_point_ids,
        )

    request = Request(
        resident_id=user.id,
        key_type=payload.key_type,
        key_value=payload.key_value,
        gate_key_id=gate_key_id,
        access_point_ids=payload.access_point_ids,
        is_permanent=is_permanent,
        expires_at=expires_at,
        status="active",
        plot_number=payload.plot_number,
    )
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return request


async def list_my_requests(session: AsyncSession, user_id: int) -> list[Request]:
    query = await session.execute(
        select(Request).where(Request.resident_id == user_id).order_by(Request.created_at.desc())
    )
    return list(query.scalars().all())


async def cancel_request(session: AsyncSession, user_id: int, request_id: int) -> Request | None:
    query = await session.execute(
        select(Request).where(Request.id == request_id, Request.resident_id == user_id, Request.status == "active")
    )
    request = query.scalar_one_or_none()
    if request is None:
        return None

    request.status = "cancelled"
    request.cancelled_at = datetime.now(timezone.utc)

    other_query = await session.execute(
        select(func.count(Request.id)).where(
            and_(
                Request.id != request.id,
                Request.key_value == request.key_value,
                Request.status == "active",
            )
        )
    )
    other_active_count = int(other_query.scalar_one())
    if other_active_count == 0 and request.gate_key_id is not None:
        gate_client.remove_key(request.gate_key_id)

    await session.commit()
    await session.refresh(request)
    return request


async def has_access_to_point(session: AsyncSession, user_id: int, access_point_id: int) -> bool:
    query = await session.execute(
        select(Request).where(
            Request.resident_id == user_id,
            Request.status == "active",
        )
    )
    active_requests = list(query.scalars().all())
    now = datetime.now(timezone.utc)
    for item in active_requests:
        if access_point_id not in (item.access_point_ids or []):
            continue
        if item.is_permanent:
            return True
        if item.expires_at is None:
            return True
        if item.expires_at >= now:
            return True
    return False


async def cleanup_expired_requests(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    query = await session.execute(
        select(Request).where(
            Request.status == "active",
            Request.is_permanent.is_(False),
            Request.expires_at.is_not(None),
            Request.expires_at <= now,
        )
    )
    expired_items = list(query.scalars().all())
    if not expired_items:
        return 0

    changed = 0
    for req in expired_items:
        req.status = "expired"
        other_query = await session.execute(
            select(func.count(Request.id)).where(
                Request.id != req.id, Request.key_value == req.key_value, Request.status == "active"
            )
        )
        if int(other_query.scalar_one()) == 0 and req.gate_key_id:
            gate_client.remove_key(req.gate_key_id)
        changed += 1

    await session.commit()
    return changed
