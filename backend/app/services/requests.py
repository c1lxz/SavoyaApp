from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import and_, func, inspect, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Request, User
from ..schemas import CreateRequestRequest
from ..utils.datetime import ensure_utc_datetime, utcnow
from .gate import gate_client

settings = get_settings()

_ACTIVE_REQUEST_STATUSES = ("active",)


class RequestConflictError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RequestIntegrationError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _resolved_access_point_ids(*, key_type: str, requested_ids: list[int]) -> list[int]:
    normalized_requested = [int(item) for item in requested_ids]
    if key_type != "Phone":
        return normalized_requested
    configured_gsm = list(settings.gsm_access_point_ids)
    return configured_gsm or normalized_requested


def resolve_request_status(is_permanent: bool, expires_at: datetime | None) -> str:
    if is_permanent:
        return "permanent"
    normalized_expires_at = ensure_utc_datetime(expires_at)
    if normalized_expires_at and normalized_expires_at < utcnow():
        return "expired"
    return "active"


async def ensure_active_request_unique_index(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_requests_active_key
        ON requests (key_type, key_value)
        WHERE status = 'active'
        """
        )
    )
    await session.commit()


async def ensure_requests_schema(session: AsyncSession) -> None:
    connection = await session.connection()

    def _get_columns(sync_connection) -> set[str]:
        return {str(column["name"]) for column in inspect(sync_connection).get_columns("requests")}

    columns = await connection.run_sync(_get_columns)
    if "is_courier" not in columns:
        await session.execute(text("ALTER TABLE requests ADD COLUMN is_courier BOOLEAN NOT NULL DEFAULT 0"))
        await session.commit()
    if "contact_phone" not in columns:
        await session.execute(text("ALTER TABLE requests ADD COLUMN contact_phone VARCHAR(32) NULL"))
        await session.commit()


async def cleanup_broken_requests(session: AsyncSession) -> int:
    query = await session.execute(
        select(Request).where(Request.status == "active").order_by(Request.key_type, Request.key_value, Request.id.desc())
    )
    active_rows = list(query.scalars().all())
    if not active_rows:
        return 0

    grouped: dict[tuple[str, str], list[Request]] = defaultdict(list)
    for item in active_rows:
        grouped[(item.key_type, item.key_value)].append(item)

    changed_rows: list[Request] = []
    for rows in grouped.values():
        valid_rows = [item for item in rows if item.gate_key_id is not None and item.gate_key_id > 0]
        keep_id: int | None = valid_rows[0].id if valid_rows else None
        for item in rows:
            if keep_id is not None and item.id == keep_id:
                continue
            if item.gate_key_id is None and len(rows) == 1:
                continue
            if item.status != "active":
                continue
            item.status = "cancelled"
            item.cancelled_at = utcnow()
            changed_rows.append(item)

    if not changed_rows:
        return 0

    await session.commit()
    return len(changed_rows)


async def cleanup_duplicate_requests(session: AsyncSession) -> int:
    query = await session.execute(
        select(Request).where(Request.status == "active").order_by(Request.key_type, Request.key_value, Request.id.desc())
    )
    active_rows = list(query.scalars().all())
    if not active_rows:
        return 0

    grouped: dict[tuple[str, str], list[Request]] = defaultdict(list)
    for item in active_rows:
        grouped[(item.key_type, item.key_value)].append(item)

    changed_rows: list[Request] = []
    for rows in grouped.values():
        if len(rows) < 2:
            continue

        valid_rows = [item for item in rows if item.gate_key_id is not None and item.gate_key_id > 0]
        keep_id = valid_rows[0].id if valid_rows else None
        for item in rows:
            if keep_id is not None and item.id == keep_id:
                continue
            item.status = "cancelled"
            item.cancelled_at = utcnow()
            changed_rows.append(item)

    if not changed_rows:
        return 0

    await session.commit()
    return len(changed_rows)


async def _ensure_no_duplicate_active_request(
    session: AsyncSession,
    *,
    key_type: str,
    key_value: str,
) -> None:
    query = await session.execute(
        select(Request.id).where(
            Request.key_type == key_type,
            Request.key_value == key_value,
            Request.status.in_(_ACTIVE_REQUEST_STATUSES),
        )
    )
    existing_id = query.scalar_one_or_none()
    if existing_id is not None:
        raise RequestConflictError(
            code="duplicate_request",
            message=f"An active request already exists for {key_value}",
        )


async def create_request(session: AsyncSession, user: User, payload: CreateRequestRequest) -> Request:
    resolved_access_point_ids = _resolved_access_point_ids(
        key_type=payload.key_type,
        requested_ids=payload.access_point_ids,
    )

    await _ensure_no_duplicate_active_request(
        session,
        key_type=payload.key_type,
        key_value=payload.key_value,
    )

    is_permanent = payload.is_permanent
    request_hours = payload.hours

    if payload.is_courier and settings.courier_ttl_only_enabled:
        is_permanent = False
        base_hours = request_hours if request_hours is not None else settings.courier_default_hours
        request_hours = min(base_hours, settings.courier_max_hours)

    expires_at: datetime | None = None
    if not is_permanent:
        hours = request_hours if request_hours is not None else 24
        expires_at = utcnow() + timedelta(hours=hours)

    try:
        if is_permanent:
            gate_key_id = gate_client.add_permanent_key(
                key_type=payload.key_type,
                key_value=payload.key_value,
                phone_number=payload.phone_number,
                access_point_ids=resolved_access_point_ids,
                resident_name=user.name or user.login or "Resident",
            )
        else:
            gate_key_id = gate_client.add_temporary_key(
                key_type=payload.key_type,
                key_value=payload.key_value,
                phone_number=payload.phone_number,
                expires_at=expires_at,
                access_point_ids=resolved_access_point_ids,
                resident_name=user.name or user.login or "Resident",
            )
    except Exception as exc:
        raise RequestIntegrationError(
            code="gate_bridge_error",
            message="Gate integration failed",
        ) from exc

    if gate_key_id <= 0:
        raise RequestIntegrationError(
            code="invalid_gate_key",
            message=f"Gate returned invalid key id: {gate_key_id}",
        )

    request = Request(
        resident_id=user.id,
        key_type=payload.key_type,
        key_value=payload.key_value,
        gate_key_id=gate_key_id,
        access_point_ids=resolved_access_point_ids,
        is_permanent=is_permanent,
        is_courier=payload.is_courier,
        contact_phone=payload.phone_number,
        expires_at=expires_at,
        status="active",
        plot_number=payload.plot_number,
    )
    session.add(request)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        gate_client.remove_key(gate_key_id)
        raise RequestConflictError(
            code="duplicate_request",
            message=f"An active request already exists for {payload.key_value}",
        ) from exc
    except Exception:
        await session.rollback()
        gate_client.remove_key(gate_key_id)
        raise

    await session.refresh(request)
    return request


async def list_my_requests(session: AsyncSession, user_id: int) -> list[Request]:
    query = await session.execute(
        select(Request).where(Request.resident_id == user_id).order_by(Request.created_at.desc())
    )
    return list(query.scalars().all())


async def list_requests_for_admin(
    session: AsyncSession,
    *,
    search: str | None = None,
    status: str | None = None,
    key_type: str | None = None,
    resident_login: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[tuple[Request, User]]]:
    filters = []

    normalized_status = (status or "").strip().lower()
    if normalized_status:
        if normalized_status == "permanent":
            filters.append(Request.is_permanent.is_(True))
        else:
            filters.append(Request.status == normalized_status)

    normalized_key_type = (key_type or "").strip()
    if normalized_key_type:
        filters.append(Request.key_type == normalized_key_type)

    normalized_resident_login = (resident_login or "").strip().lower()
    if normalized_resident_login:
        filters.append(func.lower(User.login) == normalized_resident_login)

    normalized_search = (search or "").strip()
    if normalized_search:
        like_pattern = f"%{normalized_search}%"
        filters.append(
            or_(
                Request.key_value.ilike(like_pattern),
                Request.contact_phone.ilike(like_pattern),
                Request.plot_number.ilike(like_pattern),
                User.login.ilike(like_pattern),
                User.name.ilike(like_pattern),
                User.phone.ilike(like_pattern),
                User.plot_number.ilike(like_pattern),
            )
        )

    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    total_query = select(func.count(Request.id)).select_from(Request).join(User, User.id == Request.resident_id)
    if filters:
        total_query = total_query.where(*filters)
    total = int((await session.execute(total_query)).scalar_one())

    list_query = (
        select(Request, User)
        .join(User, User.id == Request.resident_id)
        .order_by(Request.created_at.desc(), Request.id.desc())
        .limit(safe_limit)
        .offset(safe_offset)
    )
    if filters:
        list_query = list_query.where(*filters)

    rows = await session.execute(list_query)
    return total, list(rows.all())


async def cancel_request(session: AsyncSession, user_id: int, request_id: int) -> Request | None:
    query = await session.execute(
        select(Request).where(Request.id == request_id, Request.resident_id == user_id, Request.status == "active")
    )
    request = query.scalar_one_or_none()
    if request is None:
        return None

    request.status = "cancelled"
    request.cancelled_at = utcnow()

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
    now = utcnow()
    for item in active_requests:
        if access_point_id not in (item.access_point_ids or []):
            continue
        if item.is_permanent:
            return True
        normalized_expires_at = ensure_utc_datetime(item.expires_at)
        if normalized_expires_at is None:
            return True
        if normalized_expires_at >= now:
            return True
    return False


async def cleanup_expired_requests(session: AsyncSession) -> int:
    now = utcnow()
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
