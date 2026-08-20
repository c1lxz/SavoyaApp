from __future__ import annotations

import asyncio
import logging
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
from ..utils.vehicle_number import compact_vehicle_number
from .gate import GateOpenResult, gate_client

settings = get_settings()
logger = logging.getLogger(__name__)
OPEN_ACTION = "open"
STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

_RATE_WINDOW_SECONDS = 60
_RATE_MAX_EVENTS = 12
_DUPLICATE_WINDOW_SECONDS = 5
_BARRIER_COOLDOWN_SECONDS = 15
_WICKET_COOLDOWN_SECONDS = 15
# Gate event codes that mean a cardholder was let through.  A camera/LPR entry emits
# both 2 ("Проход по ключу разрешен" — access granted) and 8 ("Проход совершен" —
# passage completed); accept either so a courier driving in via the camera is detected
# even if only one of the two events is in the polled window.
_GATE_PASS_GRANTED_CODES = frozenset({2, 8})
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


@dataclass
class ResolvedAccessContext:
    access_point: AccessPoint
    access_key: AccessKey
    request_item: Request | None
    key_external_id: str
    key_type: str
    key_value: str
    source: str


def _utcnow() -> datetime:
    return utcnow()


def _merge_access_point_ids(*groups: list[int]) -> list[int]:
    merged: list[int] = []
    seen: set[int] = set()
    for group in groups:
        for item in group:
            point_id = int(item)
            if point_id <= 0 or point_id in seen:
                continue
            seen.add(point_id)
            merged.append(point_id)
    return merged


def _account_access_point_ids() -> list[int]:
    return _merge_access_point_ids(list(settings.default_access_point_ids), list(settings.gsm_access_point_ids))


def _request_priority(item: Request, *, prefer_courier: bool) -> tuple[int, int, float]:
    created_at = ensure_utc_datetime(item.created_at) or datetime.fromtimestamp(0, tz=timezone.utc)
    is_courier = bool(getattr(item, "is_courier", False))
    # At barrier_exit (prefer_courier=True):  courier passes rank 0 (preferred), non-courier rank 1.
    # At barrier_entry (prefer_courier=False): non-courier passes rank 0 (preferred), courier rank 1.
    # This prevents a courier/taxi pass from triggering the 2-hour entry countdown when a
    # non-courier personal pass is also available and the resident opens the barrier themselves.
    courier_rank = (0 if is_courier else 1) if prefer_courier else (1 if is_courier else 0)
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
        points = await asyncio.to_thread(gate_client.get_access_points)
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


async def _get_or_create_access_key_by_external_id(
    session: AsyncSession,
    *,
    user_id: int,
    external_id: str,
    valid_from: datetime | None,
    valid_to: datetime | None,
    protocol_type: str = "gate_mdb_user",
) -> AccessKey:
    query = await session.execute(
        select(AccessKey).where(
            AccessKey.user_id == user_id,
            AccessKey.external_id == external_id,
            AccessKey.is_active.is_(True),
        )
    )
    key = query.scalar_one_or_none()
    if key is not None:
        return key

    key = AccessKey(
        user_id=user_id,
        external_id=external_id,
        protocol_type=protocol_type,
        is_active=True,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    session.add(key)
    await session.flush()
    return key


async def _get_or_create_access_key(session: AsyncSession, request_item: Request) -> AccessKey:
    return await _get_or_create_access_key_by_external_id(
        session,
        user_id=request_item.resident_id,
        external_id=str(request_item.gate_key_id),
        valid_from=request_item.created_at,
        valid_to=request_item.expires_at,
    )


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
) -> ResolvedAccessContext:
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
    with_key = [item for item in matching if item.gate_key_id is not None]
    if with_key:
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
        return ResolvedAccessContext(
            access_point=access_point,
            access_key=access_key,
            request_item=primary,
            key_external_id=str(access_key.external_id or primary.gate_key_id),
            key_type=primary.key_type,
            key_value=primary.key_value,
            source="request",
        )

    account_access_point_ids = _account_access_point_ids()
    if access_point.id not in account_access_point_ids:
        if matching:
            raise AccessServiceError(code="key_not_found", message="Active key not found", http_status=404)
        raise AccessServiceError(code="forbidden", message="No access to this point", http_status=403)

    user = await session.get(User, user_id)
    if user is None:
        raise AccessServiceError(code="user_not_found", message="User not found", http_status=404)
    if not (user.phone or "").strip():
        raise AccessServiceError(
            code="account_phone_required",
            message="Account phone is required for account access",
            http_status=403,
        )

    gate_key_id = user.gate_user_id
    if gate_key_id is None:
        try:
            gate_key_id = gate_client.add_account_phone_key(
                key_value=user.phone,
                phone_number=user.phone,
                access_point_ids=account_access_point_ids,
                resident_name=user.name or user.login or "Resident",
                plot_number=user.plot_number or user.apartment,
            )
        except Exception as exc:
            raise AccessServiceError(
                code="gate_bridge_error",
                message=f"Failed to provision account gate access: {exc}",
                http_status=502,
            ) from exc

        if gate_key_id <= 0:
            raise AccessServiceError(
                code="invalid_gate_key",
                message=f"Gate returned invalid key id for account access: {gate_key_id}",
                http_status=502,
            )

        user.gate_user_id = gate_key_id
        session.add(user)
        await session.flush()

    access_key = await _get_or_create_access_key_by_external_id(
        session,
        user_id=user.id,
        external_id=str(gate_key_id),
        valid_from=user.created_at,
        valid_to=None,
        protocol_type="gate_account_phone",
    )
    await _ensure_permission(
        session,
        user_id=user.id,
        access_point_id=access_point_id,
        key_id=access_key.id,
        valid_from=user.created_at,
        valid_to=None,
    )
    await session.commit()
    return ResolvedAccessContext(
        access_point=access_point,
        access_key=access_key,
        request_item=None,
        key_external_id=str(gate_key_id),
        key_type="Phone",
        key_value=user.phone,
        source="account",
    )


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
        # Only pair opposite key types:
        #   vehicle entry  → find the companion Phone pass (same phone number stored in key_value)
        #   phone entry    → find the companion VehicleNumber pass (same phone in contact_phone)
        # Vehicle → vehicle pairing is intentionally skipped: two separate courier vehicles on
        # the same account that share a contact phone are independent passes (e.g. a taxi pass
        # and a courier pass).  Linking their timers is incorrect — only a phone+vehicle pair
        # representing the same physical person/trip should share the entry TTL.
        if request_item.key_type == "VehicleNumber":
            is_companion = row.key_type == "Phone" and row.key_value == phone_value
        else:
            is_companion = row.key_type == "VehicleNumber" and row.contact_phone == phone_value
        if is_companion:
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
    return event_code in _GATE_PASS_GRANTED_CODES and user_ptr is not None and user_ptr > 0


def _gate_event_vehicle_plate(event: dict) -> str:
    """Best-effort canonical plate for a gate event.

    Prefers the resolved ``key_value``; falls back to the leading token of the
    event ``name`` (which gate formats as ``"PLATE   FIO"``).
    """
    raw = str(event.get("key_value") or "").strip()
    if not raw:
        name = str(event.get("name") or "").strip()
        raw = name.split()[0] if name.split() else ""
    return compact_vehicle_number(raw)


async def _find_courier_request_for_gate_event(
    session: AsyncSession,
    *,
    gate_key_id: int,
    event: dict,
) -> Request | None:
    """Find the active courier request a gate entry event belongs to.

    Primary match is the gate user pointer recorded at provisioning time.  The
    pointer can drift (e.g. the vehicle user gets recreated during provisioning or
    a maintenance repair), so fall back to matching the camera event to the courier
    pass by its vehicle plate, which is stable.
    """
    query = await session.execute(
        select(Request).where(
            Request.status == "active",
            Request.is_courier.is_(True),
            Request.gate_key_id == gate_key_id,
        )
    )
    request_item = query.scalars().first()
    if request_item is not None:
        return request_item

    event_plate = _gate_event_vehicle_plate(event)
    if not event_plate:
        return None
    plate_query = await session.execute(
        select(Request).where(
            Request.status == "active",
            Request.is_courier.is_(True),
            Request.key_type == "VehicleNumber",
        )
    )
    for candidate in plate_query.scalars().all():
        if compact_vehicle_number(candidate.key_value) == event_plate:
            return candidate
    return None


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
    already_scheduled: set[int] | None = None,
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

    request_item = await _find_courier_request_for_gate_event(
        session,
        gate_key_id=gate_key_id,
        event=event,
    )
    if request_item is None or access_point_id not in (request_item.access_point_ids or []):
        return []
    # A single camera entry emits both code 2 and code 8 for the same courier; only
    # schedule the first one seen within a poll batch.
    if already_scheduled is not None and request_item.id in already_scheduled:
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

    try:
        await sync_access_points(session)
    except Exception:
        logger.warning(
            "Failed to sync access points from Gate before courier event processing; "
            "continuing with configured/local access point data",
            exc_info=True,
        )
    already_scheduled: set[int] = set()
    for event in sorted(candidate_events, key=lambda item: _gate_event_int(item, "index") or 0):
        scheduled_request_ids = await process_courier_gate_entry_event(
            session, event, sync_points=False, already_scheduled=already_scheduled
        )
        already_scheduled.update(scheduled_request_ids)
        scheduled_count += len(scheduled_request_ids)
    return scheduled_count


async def list_my_access_points(session: AsyncSession, *, user_id: int) -> list[AccessPoint]:
    await sync_access_points(session)
    query = await session.execute(select(Request).where(Request.resident_id == user_id, Request.status == "active"))
    rows = list(query.scalars().all())
    now = _utcnow()

    allowed_ids: set[int] = set(_account_access_point_ids())
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


def _is_wicket_access_point(access_point: AccessPoint) -> bool:
    if access_point.type == "wicket":
        return True
    if access_point.type in {"barrier_entry", "barrier_exit"}:
        return False
    normalized_name = (access_point.name or "").lower()
    return "wicket" in normalized_name or "калит" in normalized_name


def _cooldown_message(access_point: AccessPoint, remaining_seconds: int) -> str:
    # Distinguish wicket vs barrier by type/name (the cooldown durations are equal, so
    # comparing seconds cannot tell them apart) and make the demonstrative pronoun agree
    # in gender: "этой калитки" (fem.) vs "этого шлагбаума" (masc.).
    if _is_wicket_access_point(access_point):
        pronoun, point_label = "этой", "калитки"
    else:
        pronoun, point_label = "этого", "шлагбаума"
    return f"Подождите {remaining_seconds} сек. перед повторным открытием {pronoun} {point_label}."


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

    context = await _resolve_access_context(
        session,
        user_id=user_id,
        access_point_id=access_point_id,
    )
    access_point = context.access_point
    access_key = context.access_key
    request_item = context.request_item
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
            "request_db_id": request_item.id if request_item is not None else None,
            "gate_key_id": int(context.key_external_id),
            "key_external_id": access_key.external_id,
            "key_type": context.key_type,
            "key_value": context.key_value,
            "access_source": context.source,
            "actor_login": user.login if user is not None else None,
            "actor_name": user.name if user is not None else None,
            "actor_phone": user.phone if user is not None else None,
            "transport": "gateterm_ui",
        },
    )
    session.add(event)
    await session.commit()

    try:
        # FIX: wrap in asyncio.to_thread — open_access_point is now in _MUTATING_BRIDGE_ACTIONS
        # and acquires _mutating_bridge_lock (threading.Lock).  Calling it directly on the
        # event loop thread would block the entire event loop for the bridge timeout (up to 60s),
        # stalling all other requests including a second concurrent open_access_point call.
        result = await asyncio.to_thread(
            gate_client.open_access_point, access_point.id, key_external_id=access_key.external_id
        )
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
    if (
        not result.success
        and context.source == "account"
        and result.code in {"key_not_found", "access_denied"}
        and (user.phone or "").strip()
    ):
        try:
            refreshed_gate_key_id = gate_client.add_account_phone_key(
                key_value=user.phone,
                phone_number=user.phone,
                access_point_ids=_account_access_point_ids(),
                resident_name=user.name or user.login or "Resident",
                plot_number=user.plot_number or user.apartment,
            )
            if refreshed_gate_key_id > 0:
                user.gate_user_id = refreshed_gate_key_id
                session.add(user)
                access_key.external_id = str(refreshed_gate_key_id)
                access_key.protocol_type = "gate_account_phone"
                await session.commit()
                context.key_external_id = str(refreshed_gate_key_id)
                result = await asyncio.to_thread(
                    gate_client.open_access_point, access_point.id, key_external_id=access_key.external_id
                )
        except Exception as exc:
            result = GateOpenResult(
                success=False,
                message=f"Gate bridge error: {exc}",
                code="gate_bridge_error",
                details={
                    "transport": event.details.get("transport") if event.details else "unknown",
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "retry_mode": "refresh_account_access",
                },
            )
    event.status = STATUS_SUCCESS if result.success else STATUS_FAILED
    event.error_code = result.code if not result.success else None
    event.error_message = result.message if not result.success else None
    event.details = {
        **(event.details or {}),
        "gate_key_id": int(context.key_external_id),
        "key_external_id": access_key.external_id,
        **({"gate_result": result.details} if result.details else {}),
    }
    cleanup_error: str | None = None
    if (
        result.success
        and request_item is not None
        and access_point.type == "barrier_entry"
        and bool(getattr(request_item, "is_courier", False))
    ):
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
