from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, inspect, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import AccessEventLog, AccessKey, AccessPermission, Request, User
from ..schemas import CreateRequestRequest
from ..utils.datetime import ensure_utc_datetime, utcnow
from ..utils.input_safety import normalize_phone_key
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


def _merge_access_point_ids(*groups: list[int]) -> list[int]:
    merged: list[int] = []
    seen: set[int] = set()
    for group in groups:
        for item in group:
            point_id = int(item)
            if point_id in seen:
                continue
            seen.add(point_id)
            merged.append(point_id)
    return merged


def _resolved_access_point_ids(*, key_type: str, requested_ids: list[int]) -> list[int]:
    normalized_requested = _merge_access_point_ids(requested_ids)
    if key_type != "Phone":
        return normalized_requested
    configured_gsm = list(settings.gsm_access_point_ids)
    return _merge_access_point_ids(normalized_requested, configured_gsm)


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


async def ensure_admin_permanent_request(session: AsyncSession) -> Request | None:
    if not settings.bootstrap_admin_user:
        return None
    if not settings.admin_login.strip() or not settings.admin_phone.strip():
        return None

    admin_query = await session.execute(select(User).where(User.login == settings.admin_login, User.is_admin.is_(True)))
    admin = admin_query.scalar_one_or_none()
    if admin is None:
        return None

    key_value = normalize_phone_key(settings.admin_phone)
    access_point_ids = _resolved_access_point_ids(
        key_type="Phone",
        requested_ids=list(settings.default_access_point_ids),
    )

    query = await session.execute(
        select(Request).where(
            Request.key_type == "Phone",
            Request.key_value == key_value,
            Request.status == "active",
        )
    )
    existing = query.scalar_one_or_none()
    if existing is not None and existing.resident_id != admin.id:
        return None

    gate_key_id = await asyncio.to_thread(
        gate_client.add_permanent_key,
        key_type="Phone",
        key_value=key_value,
        phone_number=key_value,
        access_point_ids=access_point_ids,
        resident_name=admin.name or admin.login or "Admin",
        plot_number=admin.plot_number or admin.apartment or settings.admin_plot_number,
    )

    if existing is None:
        existing = Request(
            resident_id=admin.id,
            key_type="Phone",
            key_value=key_value,
            gate_key_id=gate_key_id,
            access_point_ids=access_point_ids,
            is_permanent=True,
            is_courier=False,
            contact_phone=key_value,
            expires_at=None,
            status="active",
            plot_number=admin.plot_number or admin.apartment or settings.admin_plot_number,
        )
        session.add(existing)
    else:
        existing.gate_key_id = gate_key_id
        existing.access_point_ids = access_point_ids
        existing.is_permanent = True
        existing.is_courier = False
        existing.contact_phone = key_value
        existing.expires_at = None
        existing.plot_number = admin.plot_number or admin.apartment or settings.admin_plot_number

    await session.commit()
    await session.refresh(existing)
    return existing


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
    requested_expires_at = ensure_utc_datetime(payload.expires_at)
    now = utcnow()

    if payload.is_courier and settings.courier_ttl_only_enabled:
        is_permanent = False
        if requested_expires_at is not None:
            max_expires_at = now + timedelta(hours=settings.courier_max_hours)
            requested_expires_at = min(requested_expires_at, max_expires_at)
        else:
            base_hours = request_hours if request_hours is not None else settings.courier_default_hours
            request_hours = min(base_hours, settings.courier_max_hours)

    expires_at: datetime | None = None
    if not is_permanent:
        if requested_expires_at is not None:
            if requested_expires_at <= now:
                raise RequestIntegrationError(
                    code="invalid_expires_at",
                    message="Pass expiry must be in the future",
                )
            expires_at = requested_expires_at
        else:
            hours = request_hours if request_hours is not None else 24
            expires_at = now + timedelta(hours=hours)

    try:
        resident_name = (payload.resident_name or "").strip() or user.name or user.login or "Resident"
        if is_permanent:
            gate_key_id = gate_client.add_permanent_key(
                key_type=payload.key_type,
                key_value=payload.key_value,
                phone_number=payload.phone_number,
                access_point_ids=resolved_access_point_ids,
                resident_name=resident_name,
                plot_number=payload.plot_number,
            )
        else:
            gate_key_id = gate_client.add_temporary_key(
                key_type=payload.key_type,
                key_value=payload.key_value,
                phone_number=payload.phone_number,
                expires_at=expires_at,
                access_point_ids=resolved_access_point_ids,
                resident_name=resident_name,
                plot_number=payload.plot_number,
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


async def delete_request_for_admin(session: AsyncSession, request_id: int) -> Request | None:
    query = await session.execute(select(Request).where(Request.id == request_id))
    request = query.scalar_one_or_none()
    if request is None:
        return None

    gate_key_id = int(request.gate_key_id) if request.gate_key_id is not None else None
    key_ids: list[int] = []
    if gate_key_id is not None:
        key_query = await session.execute(
            select(AccessKey).where(
                AccessKey.user_id == request.resident_id,
                AccessKey.external_id == str(gate_key_id),
            )
        )
        key_ids = [int(item.id) for item in key_query.scalars().all()]

    other_active_count = 0
    if gate_key_id is not None:
        other_query = await session.execute(
            select(func.count(Request.id)).where(
                and_(
                    Request.id != request.id,
                    Request.gate_key_id == gate_key_id,
                    Request.status == "active",
                )
            )
        )
        other_active_count = int(other_query.scalar_one() or 0)

    user = await session.get(User, request.resident_id)
    if user is not None and gate_key_id is not None and user.gate_user_id == gate_key_id:
        user.gate_user_id = None
        session.add(user)

    if key_ids:
        await session.execute(update(AccessEventLog).where(AccessEventLog.key_id.in_(key_ids)).values(key_id=None))
        await session.execute(delete(AccessPermission).where(AccessPermission.key_id.in_(key_ids)))
        await session.execute(delete(AccessKey).where(AccessKey.id.in_(key_ids)))

    await session.delete(request)
    await session.flush()

    if other_active_count == 0 and gate_key_id is not None:
        gate_client.remove_key(gate_key_id)

    await session.commit()
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
    if access_point_id in _merge_access_point_ids(list(settings.default_access_point_ids), list(settings.gsm_access_point_ids)):
        return True
    return False


async def cleanup_expired_requests(session: AsyncSession, *, remove_gate_keys: bool = True) -> int:
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
            key_query = await session.execute(
                select(AccessKey).where(
                    AccessKey.user_id == req.resident_id,
                    AccessKey.external_id == str(req.gate_key_id),
                    AccessKey.is_active.is_(True),
                )
            )
            keys = list(key_query.scalars().all())
            key_ids = [key.id for key in keys]
            for key in keys:
                key.is_active = False
            if key_ids:
                permissions_query = await session.execute(select(AccessPermission).where(AccessPermission.key_id.in_(key_ids)))
                for permission in permissions_query.scalars().all():
                    permission.is_allowed = False
            if remove_gate_keys:
                gate_client.remove_key(req.gate_key_id)
        changed += 1

    await session.commit()
    return changed
