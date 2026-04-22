from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import AccessEventLog, AccessKey, AccessPermission, AccessPoint, Request, User
from ..utils.datetime import ensure_utc_datetime, utcnow
from .gate import GateOpenResult, gate_client

settings = get_settings()
OPEN_ACTION = "open"
STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

_RATE_WINDOW_SECONDS = 60
_RATE_MAX_EVENTS = 12
_DUPLICATE_WINDOW_SECONDS = 5
_BARRIER_COOLDOWN_SECONDS = 15
_WICKET_COOLDOWN_SECONDS = 15
_GATE_PASS_GRANTED_CODE = 2
_GATE_EVENT_TIMEZONE = ZoneInfo("Europe/Moscow")
_SYNC_ACCESS_POINTS_LOCK = asyncio.Lock()


class AccessServiceError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        http_status: int,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


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
    async with _SYNC_ACCESS_POINTS_LOCK:
        points = gate_client.get_access_points()
        for point in points:
            point_id = int(point["id"])
            point_name = str(point["name"])
            point_type = _normalize_access_point_type(point_name)
            existing = await session.get(AccessPoint, point_id)
            if existing is None:
                session.add(
                    AccessPoint(
                        id=point_id,
                        name=point_name,
                        code=f"gate_{point_id}",
                        type=point_type,
                        is_active=True,
                    )
                )
                continue
            existing.name = point_name
            existing.type = point_type
            existing.is_active = True
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            for point in points:
                point_id = int(point["id"])
                point_name = str(point["name"])
                point_type = _normalize_access_point_type(point_name)
                existing = await session.get(AccessPoint, point_id)
                if existing is None:
                    continue
                existing.name = point_name
                existing.type = point_type
                existing.is_active = True
            await session.commit()


def _normalize_access_point_type(name: str) -> str:
    value = (name or "").lower()
    if "камера" in value or "шлагбаум" in value or "gsm" in value or "транспондер" in value:
        if "въезд" in value or "entry" in value:
            return "barrier_entry"
        if "выезд" in value or "exit" in value:
            return "barrier_exit"
    if (
        "калит" in value
        or "вход " in value
        or value.startswith("вход")
        or "выход " in value
        or value.startswith("выход")
        or "север" in value
        or "лес" in value
        or "озер" in value
    ):
        return "wicket"
    return _infer_access_point_type(name)


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


async def _courier_companion_candidates(
    session: AsyncSession,
    *,
    request_item: Request,
    access_point_id: int,
) -> list[Request]:
    candidates = [request_item]
    phone_value = request_item.key_value if request_item.key_type == "Phone" else request_item.contact_phone
    if not phone_value:
        return candidates

    query = await session.execute(
        select(Request).where(
            Request.resident_id == request_item.resident_id,
            Request.status == "active",
            Request.is_courier.is_(True),
            Request.id != request_item.id,
        )
    )
    for row in query.scalars().all():
        if request_item.plot_number and row.plot_number and request_item.plot_number != row.plot_number:
            continue
        is_companion_phone = row.key_type == "Phone" and row.key_value == phone_value
        is_companion_vehicle = row.key_type == "VehicleNumber" and row.contact_phone == phone_value
        if is_companion_phone or is_companion_vehicle:
            candidates.append(row)

    return candidates


async def _schedule_courier_requests_after_entry(
    session: AsyncSession,
    *,
    request_item: Request,
    access_point_id: int,
    entry_at: datetime | None = None,
) -> tuple[list[int], datetime]:
    candidates = await _courier_companion_candidates(
        session,
        request_item=request_item,
        access_point_id=access_point_id,
    )

    base_time = ensure_utc_datetime(entry_at) or utcnow()
    expires_at = base_time + timedelta(hours=settings.courier_default_hours)
    scheduled_ids: list[int] = []
    gate_key_ids: list[str] = []
    for row in candidates:
        row.is_permanent = False
        row.expires_at = expires_at
        scheduled_ids.append(int(row.id))
        if row.gate_key_id is not None:
            gate_key_ids.append(str(row.gate_key_id))

    if gate_key_ids:
        keys_query = await session.execute(
            select(AccessKey).where(
                AccessKey.user_id == request_item.resident_id,
                AccessKey.external_id.in_(gate_key_ids),
                AccessKey.is_active.is_(True),
            )
        )
        keys = list(keys_query.scalars().all())
        key_ids = [key.id for key in keys]
        for key in keys:
            key.valid_to = expires_at
        if key_ids:
            permissions_query = await session.execute(select(AccessPermission).where(AccessPermission.key_id.in_(key_ids)))
            for permission in permissions_query.scalars().all():
                permission.valid_to = expires_at

    return scheduled_ids, expires_at


def _gate_event_int(event: dict, key: str) -> int | None:
    value = event.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_gate_pass_granted_event(event: dict) -> bool:
    event_type = _gate_event_int(event, "event_type")
    event_code = _gate_event_int(event, "event_code")
    user_ptr = _gate_event_int(event, "user_ptr")
    if event_type is not None and event_type != 1:
        return False
    return event_code == _GATE_PASS_GRANTED_CODE and user_ptr is not None and user_ptr > 0


def _configured_access_point_type(access_point_id: int | None) -> str | None:
    if access_point_id is None:
        return None
    action_map = settings.gate_action_map
    if action_map.get("entry") == access_point_id:
        return "barrier_entry"
    if action_map.get("exit") == access_point_id:
        return "barrier_exit"
    for action in ("wicket_north", "wicket_lake", "wicket_admin", "wicket_forest"):
        if action_map.get(action) == access_point_id:
            return "wicket"
    return None


def _gate_event_point_name(event: dict, access_point: AccessPoint | None) -> str:
    parts = [
        getattr(access_point, "name", None),
        event.get("unit"),
        event.get("access_point_name"),
        event.get("reader_name"),
        event.get("point_name"),
    ]
    return " ".join(str(part) for part in parts if part)


def _is_gate_pass_event_for_type(
    event: dict,
    access_point: AccessPoint | None,
    access_point_type: str,
) -> bool:
    if not _is_gate_pass_granted_event(event):
        return False
    if access_point is not None:
        if access_point.type == access_point_type:
            return True

    configured_type = _configured_access_point_type(_gate_event_int(event, "access_point_id"))
    if configured_type == access_point_type:
        return True

    return _normalize_access_point_type(_gate_event_point_name(event, access_point)) == access_point_type


def _gate_event_time_utc(event: dict) -> datetime | None:
    raw_value = event.get("time")
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        value = raw_value
    else:
        try:
            value = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        value = value.replace(tzinfo=_GATE_EVENT_TIMEZONE)
    return value.astimezone(timezone.utc)


async def process_courier_gate_entry_event(
    session: AsyncSession,
    event: dict,
    *,
    sync_points: bool = True,
) -> list[int]:
    access_point_id = _gate_event_int(event, "access_point_id")
    gate_key_id = _gate_event_int(event, "user_ptr")
    if access_point_id is None or gate_key_id is None:
        return []
    if not _is_gate_pass_granted_event(event):
        return []

    if sync_points:
        await sync_access_points(session)
    access_point = await session.get(AccessPoint, access_point_id)
    if not _is_gate_pass_event_for_type(event, access_point, "barrier_entry"):
        return []

    query = await session.execute(
        select(Request).where(
            Request.status == "active",
            Request.is_courier.is_(True),
            Request.gate_key_id == gate_key_id,
        )
    )
    request_item = query.scalar_one_or_none()
    if request_item is None or access_point_id not in (request_item.access_point_ids or []):
        return []
    if not _is_request_active(request_item, _utcnow()):
        return []
    event_time = _gate_event_time_utc(event)
    request_created_at = ensure_utc_datetime(request_item.created_at)
    if event_time is not None and request_created_at is not None:
        if event_time < request_created_at - timedelta(seconds=5):
            return []

    scheduled_request_ids, expires_at = await _schedule_courier_requests_after_entry(
        session,
        request_item=request_item,
        access_point_id=access_point_id,
        entry_at=event_time,
    )
    if not scheduled_request_ids:
        return []

    event_index = _gate_event_int(event, "index")
    audit_request_id = f"gate-entry-{event_index}" if event_index is not None else f"gate-entry-{uuid4()}"
    session.add(
        AccessEventLog(
            user_id=request_item.resident_id,
            access_point_id=access_point_id,
            key_id=None,
            request_id=audit_request_id,
            action="courier_gate_entry",
            status=STATUS_SUCCESS,
            details={
                "transport": "gate_event_poll",
                "gate_event": event,
                "courier_request_id": request_item.id,
                "courier_scheduled_request_ids": scheduled_request_ids,
                "courier_expires_at": expires_at.isoformat(),
                "courier_cleanup": "scheduled_after_entry",
            },
        )
    )
    await session.commit()
    return scheduled_request_ids


async def process_courier_gate_entry_events(session: AsyncSession, events: list[dict]) -> int:
    scheduled_count = 0
    candidate_events = [event for event in events if _is_gate_pass_granted_event(event)]
    if not candidate_events:
        return 0

    await sync_access_points(session)
    for event in sorted(candidate_events, key=lambda item: _gate_event_int(item, "index") or 0):
        scheduled_request_ids = await process_courier_gate_entry_event(session, event, sync_points=False)
        scheduled_count += len(scheduled_request_ids)
    return scheduled_count


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


def _cooldown_seconds_for_access_point(access_point: AccessPoint) -> int:
    if access_point.type == "wicket":
        return _WICKET_COOLDOWN_SECONDS
    if access_point.type in {"barrier_entry", "barrier_exit"}:
        return _BARRIER_COOLDOWN_SECONDS

    normalized_name = (access_point.name or "").lower()
    if "wicket" in normalized_name or "калит" in normalized_name:
        return _WICKET_COOLDOWN_SECONDS
    return _BARRIER_COOLDOWN_SECONDS


def _cooldown_message(access_point: AccessPoint, remaining_seconds: int) -> str:
    point_label = (
        "калитки"
        if _cooldown_seconds_for_access_point(access_point) == _WICKET_COOLDOWN_SECONDS
        else "шлагбаума"
    )
    return f"Подождите {remaining_seconds} сек. перед повторным открытием этого {point_label}."


async def _check_open_cooldown(session: AsyncSession, *, user: User | None, access_point: AccessPoint) -> None:
    if user is None or user.is_admin:
        return

    cooldown_seconds = _cooldown_seconds_for_access_point(access_point)
    since = _utcnow() - timedelta(seconds=cooldown_seconds)
    query = await session.execute(
        select(AccessEventLog)
        .where(
            AccessEventLog.user_id == user.id,
            AccessEventLog.access_point_id == access_point.id,
            AccessEventLog.action == OPEN_ACTION,
            AccessEventLog.status.in_([STATUS_PENDING, STATUS_SUCCESS]),
            AccessEventLog.created_at >= since,
        )
        .order_by(AccessEventLog.created_at.desc())
        .limit(1)
    )
    row = query.scalar_one_or_none()
    if row is None:
        return

    created_at = ensure_utc_datetime(row.created_at)
    if created_at is None:
        return

    elapsed_seconds = max(0.0, (_utcnow() - created_at).total_seconds())
    remaining_seconds = max(1, int(ceil(cooldown_seconds - elapsed_seconds)))
    if remaining_seconds <= 0:
        return

    raise AccessServiceError(
        code="open_cooldown",
        message=_cooldown_message(access_point, remaining_seconds),
        http_status=429,
        retry_after_seconds=remaining_seconds,
    )


async def open_access_point(session: AsyncSession, *, user_id: int, access_point_id: int) -> OpenAccessResult:
    user = await session.get(User, user_id)
    if user is None:
        raise AccessServiceError(code="user_not_found", message="User not found", http_status=404)

    if not user.is_admin:
        await _check_rate_limit(session, user_id=user_id)
    await _check_duplicate(session, user_id=user_id, access_point_id=access_point_id)

    access_point, access_key, request_item = await _resolve_access_context(
        session,
        user_id=user_id,
        access_point_id=access_point_id,
    )
    await _check_open_cooldown(session, user=user, access_point=access_point)

    request_id = str(uuid4())
    event = AccessEventLog(
        user_id=user_id,
        access_point_id=access_point.id,
        key_id=access_key.id,
        request_id=request_id,
        action=OPEN_ACTION,
        status=STATUS_PENDING,
        details={
            "access_point_code": access_point.code,
            "access_point_name": access_point.name,
            "request_db_id": request_item.id,
            "gate_key_id": request_item.gate_key_id,
            "key_external_id": access_key.external_id,
            "key_type": request_item.key_type,
            "key_value": request_item.key_value,
            "actor_login": user.login if user is not None else None,
            "actor_name": user.name if user is not None else None,
            "actor_phone": user.phone if user is not None else None,
            "transport": "gateterm_ui",
        },
    )
    session.add(event)
    await session.commit()

    try:
        result = gate_client.open_access_point(access_point.id, key_external_id=access_key.external_id)
    except Exception as exc:
        result = GateOpenResult(
            success=False,
            message=f"Gate bridge error: {exc}",
            code="gate_bridge_error",
            details={
                "transport": event.details.get("transport") if event.details else "unknown",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            },
        )
    event.status = STATUS_SUCCESS if result.success else STATUS_FAILED
    event.error_code = result.code if not result.success else None
    event.error_message = result.message if not result.success else None
    event.details = {
        **(event.details or {}),
        **({"gate_result": result.details} if result.details else {}),
    }
    cleanup_error: str | None = None
    if result.success and access_point.type == "barrier_entry" and bool(getattr(request_item, "is_courier", False)):
        try:
            scheduled_request_ids, expires_at = await _schedule_courier_requests_after_entry(
                session,
                request_item=request_item,
                access_point_id=access_point.id,
                entry_at=utcnow(),
            )
            event.details = {
                **(event.details or {}),
                "courier_request_id": request_item.id,
                "courier_scheduled_request_ids": scheduled_request_ids,
                "courier_expires_at": expires_at.isoformat(),
                "courier_cleanup": "scheduled_after_entry",
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
