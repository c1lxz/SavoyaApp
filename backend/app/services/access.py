from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AccessEventLog, AccessKey, AccessPermission, AccessPoint, Request
from ..utils.datetime import ensure_utc_datetime, utcnow
from .gate import gate_client

OPEN_ACTION = "open"
STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

_RATE_WINDOW_SECONDS = 60
_RATE_MAX_EVENTS = 12
_DUPLICATE_WINDOW_SECONDS = 5


class AccessServiceError(Exception):
    def __init__(self, *, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass
class OpenAccessResult:
    status: str
    message: str
    request_id: str


def _utcnow() -> datetime:
    return utcnow()


def _request_priority(item: Request, *, prefer_courier: bool) -> tuple[int, int, float]:
    created_at = ensure_utc_datetime(item.created_at) or datetime.fromtimestamp(0, tz=timezone.utc)
    courier_rank = 0 if prefer_courier and bool(getattr(item, "is_courier", False)) else 1
    permanent_rank = 1 if item.is_permanent else 0
    return (courier_rank, permanent_rank, -created_at.timestamp())


def _is_request_active(item: Request, now: datetime) -> bool:
    if item.status != "active":
        return False
    if item.is_permanent:
        return True
    normalized_expires_at = ensure_utc_datetime(item.expires_at)
    if normalized_expires_at is None:
        return True
    return normalized_expires_at >= now


def _infer_access_point_type(name: str) -> str:
    # HYPOTHESIS: map type by point name because source integration does not provide explicit type.
    value = (name or "").lower()
    if "entry" in value or "въезд" in value:
        return "barrier_entry"
    if "exit" in value or "выезд" in value:
        return "barrier_exit"
    if "wicket" in value or "калит" in value:
        return "wicket"
    return "gate"


async def sync_access_points(session: AsyncSession) -> None:
    points = gate_client.get_access_points()
    for point in points:
        point_id = int(point["id"])
        point_name = str(point["name"])
        existing = await session.get(AccessPoint, point_id)
        if existing is None:
            session.add(
                AccessPoint(
                    id=point_id,
                    name=point_name,
                    code=f"gate_{point_id}",
                    type=_infer_access_point_type(point_name),
                    is_active=True,
                )
            )
            continue
        existing.name = point_name
        existing.type = _infer_access_point_type(point_name)
        existing.is_active = True
    await session.commit()


async def _get_or_create_access_key(session: AsyncSession, request_item: Request) -> AccessKey:
    external_id = str(request_item.gate_key_id)
    query = await session.execute(
        select(AccessKey).where(
            AccessKey.user_id == request_item.resident_id,
            AccessKey.external_id == external_id,
            AccessKey.is_active.is_(True),
        )
    )
    key = query.scalar_one_or_none()
    if key is not None:
        return key

    key = AccessKey(
        user_id=request_item.resident_id,
        external_id=external_id,
        protocol_type="gate_mdb_user",
        is_active=True,
        valid_from=request_item.created_at,
        valid_to=request_item.expires_at,
    )
    session.add(key)
    await session.flush()
    return key


async def _ensure_permission(
    session: AsyncSession,
    *,
    user_id: int,
    access_point_id: int,
    key_id: int,
    valid_from: datetime | None,
    valid_to: datetime | None,
) -> None:
    query = await session.execute(
        select(AccessPermission).where(
            AccessPermission.user_id == user_id,
            AccessPermission.access_point_id == access_point_id,
            AccessPermission.key_id == key_id,
        )
    )
    permission = query.scalar_one_or_none()
    if permission is None:
        session.add(
            AccessPermission(
                user_id=user_id,
                access_point_id=access_point_id,
                key_id=key_id,
                is_allowed=True,
                valid_from=valid_from,
                valid_to=valid_to,
            )
        )
        return

    permission.is_allowed = True
    permission.valid_from = valid_from
    permission.valid_to = valid_to


async def _resolve_access_context(
    session: AsyncSession, *, user_id: int, access_point_id: int
) -> tuple[AccessPoint, AccessKey, Request]:
    await sync_access_points(session)

    access_point = await session.get(AccessPoint, access_point_id)
    if access_point is None:
        raise AccessServiceError(code="access_point_not_found", message="Access point not found", http_status=404)
    if not access_point.is_active:
        raise AccessServiceError(code="access_denied", message="Access point is inactive", http_status=403)

    query = await session.execute(
        select(Request).where(
            Request.resident_id == user_id,
            Request.status == "active",
        )
    )
    rows = list(query.scalars().all())
    now = _utcnow()
    matching = [item for item in rows if access_point_id in (item.access_point_ids or []) and _is_request_active(item, now)]
    if not matching:
        raise AccessServiceError(code="forbidden", message="No access to this point", http_status=403)

    with_key = [item for item in matching if item.gate_key_id is not None]
    if not with_key:
        raise AccessServiceError(code="key_not_found", message="Active key not found", http_status=404)

    prefer_courier = access_point.type == "barrier_exit"
    primary = sorted(with_key, key=lambda item: _request_priority(item, prefer_courier=prefer_courier))[0]
    access_key = await _get_or_create_access_key(session, primary)
    await _ensure_permission(
        session,
        user_id=user_id,
        access_point_id=access_point_id,
        key_id=access_key.id,
        valid_from=primary.created_at,
        valid_to=primary.expires_at,
    )
    await session.commit()
    return access_point, access_key, primary


async def _complete_courier_request_after_exit(
    session: AsyncSession,
    *,
    request_item: Request,
    access_key: AccessKey,
) -> None:
    request_item.status = "completed"
    request_item.cancelled_at = utcnow()
    access_key.is_active = False

    permissions_query = await session.execute(
        select(AccessPermission).where(AccessPermission.key_id == access_key.id)
    )
    for permission in permissions_query.scalars().all():
        permission.is_allowed = False

    if request_item.gate_key_id is not None:
        gate_client.remove_key(int(request_item.gate_key_id))


async def list_my_access_points(session: AsyncSession, *, user_id: int) -> list[AccessPoint]:
    await sync_access_points(session)
    query = await session.execute(select(Request).where(Request.resident_id == user_id, Request.status == "active"))
    rows = list(query.scalars().all())
    now = _utcnow()

    allowed_ids: set[int] = set()
    for item in rows:
        if item.gate_key_id is None:
            continue
        if not _is_request_active(item, now):
            continue
        for point_id in item.access_point_ids or []:
            allowed_ids.add(int(point_id))

    if not allowed_ids:
        return []

    points_query = await session.execute(
        select(AccessPoint).where(and_(AccessPoint.id.in_(allowed_ids), AccessPoint.is_active.is_(True))).order_by(AccessPoint.name)
    )
    return list(points_query.scalars().all())


async def list_my_access_events(session: AsyncSession, *, user_id: int, limit: int = 100) -> list[AccessEventLog]:
    query = await session.execute(
        select(AccessEventLog)
        .where(AccessEventLog.user_id == user_id)
        .order_by(AccessEventLog.created_at.desc())
        .limit(limit)
    )
    return list(query.scalars().all())


async def _check_rate_limit(session: AsyncSession, *, user_id: int) -> None:
    since = _utcnow() - timedelta(seconds=_RATE_WINDOW_SECONDS)
    query = await session.execute(
        select(func.count(AccessEventLog.id)).where(
            AccessEventLog.user_id == user_id,
            AccessEventLog.created_at >= since,
        )
    )
    count = int(query.scalar_one())
    if count >= _RATE_MAX_EVENTS:
        raise AccessServiceError(code="too_many_requests", message="Too many open requests", http_status=429)


async def _check_duplicate(session: AsyncSession, *, user_id: int, access_point_id: int) -> None:
    since = _utcnow() - timedelta(seconds=_DUPLICATE_WINDOW_SECONDS)
    query = await session.execute(
        select(AccessEventLog)
        .where(
            AccessEventLog.user_id == user_id,
            AccessEventLog.access_point_id == access_point_id,
            AccessEventLog.created_at >= since,
            AccessEventLog.status.in_([STATUS_PENDING, STATUS_SUCCESS]),
        )
        .order_by(AccessEventLog.created_at.desc())
        .limit(1)
    )
    row = query.scalar_one_or_none()
    if row is not None:
        raise AccessServiceError(code="duplicate_request", message="Duplicate open request", http_status=409)


async def open_access_point(session: AsyncSession, *, user_id: int, access_point_id: int) -> OpenAccessResult:
    await _check_rate_limit(session, user_id=user_id)
    await _check_duplicate(session, user_id=user_id, access_point_id=access_point_id)

    access_point, access_key, request_item = await _resolve_access_context(
        session,
        user_id=user_id,
        access_point_id=access_point_id,
    )

    request_id = str(uuid4())
    event = AccessEventLog(
        user_id=user_id,
        access_point_id=access_point.id,
        key_id=access_key.id,
        request_id=request_id,
        action=OPEN_ACTION,
        status=STATUS_PENDING,
        details={"access_point_code": access_point.code},
    )
    session.add(event)
    await session.commit()

    result = gate_client.open_access_point(access_point.id, key_external_id=access_key.external_id)
    event.status = STATUS_SUCCESS if result.success else STATUS_FAILED
    event.error_code = result.code if not result.success else None
    event.error_message = result.message if not result.success else None
    event.details = {
        **(event.details or {}),
        **({"gate_result": result.details} if result.details else {}),
    }
    cleanup_error: str | None = None
    if result.success and access_point.type == "barrier_exit" and bool(getattr(request_item, "is_courier", False)):
        try:
            await _complete_courier_request_after_exit(session, request_item=request_item, access_key=access_key)
            event.details = {
                **(event.details or {}),
                "courier_request_id": request_item.id,
                "courier_cleanup": "completed",
            }
        except Exception as exc:
            cleanup_error = str(exc)
            event.details = {
                **(event.details or {}),
                "courier_request_id": request_item.id,
                "courier_cleanup": "failed",
                "courier_cleanup_error": cleanup_error,
            }
    await session.commit()

    message = result.message
    if cleanup_error:
        message = f"{message}. Courier pass cleanup failed: {cleanup_error}"
    return OpenAccessResult(status=event.status, message=message, request_id=request_id)
