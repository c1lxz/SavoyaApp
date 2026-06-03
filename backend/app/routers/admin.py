from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db_session
from ..dependencies import get_current_admin_user
from ..models import Request, User
from ..schemas import (
    AdminCreateUserPayload,
    AdminMonitorResponse,
    AdminRequestItem,
    AdminRequestListResponse,
    AdminResidentSummary,
    AdminUserItem,
    AdminUserListResponse,
    MessageResponse,
)
from ..services.admin_monitor import list_admin_monitor_events
from ..services.gate_linking import link_existing_gate_passes_by_phone
from ..services.requests import (
    delete_expired_requests,
    delete_request_for_admin,
    list_requests_for_admin,
    resolve_request_status,
)
from ..services.user_accounts import UserAccountError, build_admin_user_payload, create_user_account, delete_user_account
from ..utils.datetime import ensure_utc_datetime
from ..utils.vehicle_country import detect_vehicle_country

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _to_admin_request_item(item: Request, resident: User) -> AdminRequestItem:
    country_label = detect_vehicle_country(item.key_value) if item.key_type == "VehicleNumber" else None
    return AdminRequestItem(
        id=item.id,
        resident=AdminResidentSummary(
            id=resident.id,
            login=resident.login,
            full_name=resident.name,
            phone=resident.phone,
            plot_number=resident.plot_number or resident.apartment,
        ),
        key_type=item.key_type,
        key_value=item.key_value,
        country_label=country_label,
        phone_number=item.contact_phone,
        access_point_ids=list(item.access_point_ids or []),
        gate_key_id=item.gate_key_id,
        is_permanent=item.is_permanent,
        is_courier=item.is_courier,
        pass_kind=item.pass_kind,
        expires_at=ensure_utc_datetime(item.expires_at),
        status=resolve_request_status(item.is_permanent, item.expires_at) if item.status == "active" else item.status,
        created_at=ensure_utc_datetime(item.created_at),
        cancelled_at=ensure_utc_datetime(item.cancelled_at),
        plot_number=item.plot_number,
    )


def _to_admin_user_item(user: User) -> AdminUserItem:
    return AdminUserItem(**build_admin_user_payload(user))


@router.get("/requests", response_model=AdminRequestListResponse)
async def admin_list_requests(
    search: str | None = Query(default=None, min_length=1, max_length=100),
    status: str | None = Query(default=None, max_length=20),
    key_type: str | None = Query(default=None, max_length=20),
    resident_login: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(get_current_admin_user),
) -> AdminRequestListResponse:
    # Expired temporary passes are deleted outright (Gate key + app row), not flagged
    # "expired", so they disappear from the admin panel just like a manual deletion.
    await delete_expired_requests(session)
    total, rows = await list_requests_for_admin(
        session,
        search=search,
        status=status,
        key_type=key_type,
        resident_login=resident_login,
        limit=limit,
        offset=offset,
    )
    return AdminRequestListResponse(
        total=total,
        items=[_to_admin_request_item(request, resident) for request, resident in rows],
    )


@router.delete("/requests/{request_id}", response_model=MessageResponse)
async def admin_delete_request(
    request_id: int,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(get_current_admin_user),
) -> MessageResponse:
    deleted = await delete_request_for_admin(session, request_id)
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пропуск не найден")
    return MessageResponse(message="Пропуск удалён")


@router.get("/users", response_model=AdminUserListResponse)
async def admin_list_users(
    search: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(get_current_admin_user),
) -> AdminUserListResponse:
    filters = [User.is_admin.is_(False)]
    normalized_search = (search or "").strip()
    if normalized_search:
        exact_like_pattern = f"%{normalized_search}%"
        folded_like_pattern = f"%{normalized_search.lower()}%"
        filters.append(
            or_(
                func.coalesce(User.login, "").like(exact_like_pattern),
                func.coalesce(User.name, "").like(exact_like_pattern),
                func.coalesce(User.phone, "").like(exact_like_pattern),
                func.coalesce(User.plot_number, "").like(exact_like_pattern),
                func.lower(func.coalesce(User.login, "")).like(folded_like_pattern),
                func.lower(func.coalesce(User.name, "")).like(folded_like_pattern),
                func.lower(func.coalesce(User.phone, "")).like(folded_like_pattern),
                func.lower(func.coalesce(User.plot_number, "")).like(folded_like_pattern),
            )
        )

    total_query = select(func.count(User.id)).where(*filters)
    total = int((await session.execute(total_query)).scalar_one() or 0)

    rows_query = (
        select(User)
        .where(*filters)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(limit)
        .offset(offset)
    )
    users = list((await session.execute(rows_query)).scalars().all())

    return AdminUserListResponse(total=total, items=[_to_admin_user_item(user) for user in users])


@router.post("/users", response_model=AdminUserItem)
async def admin_create_user(
    payload: AdminCreateUserPayload,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(get_current_admin_user),
) -> AdminUserItem:
    try:
        user, generated_password = await create_user_account(
            session,
            full_name=payload.full_name,
            phone_number=payload.phone,
            plot_number=payload.plot_number,
            require_password_change=True,
        )
    except UserAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if exc.code == "phone_already_exists" else status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    if settings.gate_real_integration_enabled and user.phone and not user.is_admin:
        # The GateTerm UI phone provisioning can fail with a transient hiccup ("entered
        # data then reset"). Retry a few times with fresh attempts before giving up, so a
        # single flake does not roll the whole new account back and force a full re-entry.
        attempts = max(1, settings.gate_phone_link_attempts)
        gate_link = None
        for _attempt in range(attempts):
            gate_link = await link_existing_gate_passes_by_phone(session, user)
            if not gate_link.error and gate_link.linked_count >= 1:
                break
        if gate_link is None or gate_link.error or gate_link.linked_count < 1:
            try:
                await delete_user_account(session, user=user, strict_gate_cleanup=False)
            except Exception:
                logger.exception("Failed to roll back user after Gate phone provisioning failure", extra={"user_id": user.id})
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "gate_phone_access_failed",
                    "message": (gate_link.error if gate_link else None) or "Gate phone pass was not provisioned for the created user",
                },
            )
    return AdminUserItem(**build_admin_user_payload(user, visible_password_override=generated_password))


@router.post("/users/{user_id}/block", response_model=AdminUserItem)
async def admin_block_user(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(get_current_admin_user),
) -> AdminUserItem:
    query = await session.execute(select(User).where(User.id == user_id, User.is_admin.is_(False)))
    user = query.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    user.is_active = False
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _to_admin_user_item(user)


@router.post("/users/{user_id}/unblock", response_model=AdminUserItem)
async def admin_unblock_user(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(get_current_admin_user),
) -> AdminUserItem:
    query = await session.execute(select(User).where(User.id == user_id, User.is_admin.is_(False)))
    user = query.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    user.is_active = True
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _to_admin_user_item(user)


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def admin_delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(get_current_admin_user),
) -> MessageResponse:
    query = await session.execute(select(User).where(User.id == user_id, User.is_admin.is_(False)))
    user = query.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    try:
        await delete_user_account(session, user=user)
    except UserAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return MessageResponse(message="Пользователь удалён")


@router.get("/monitor", response_model=AdminMonitorResponse)
async def admin_monitor(
    limit: int = Query(default=120, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(get_current_admin_user),
) -> AdminMonitorResponse:
    return await list_admin_monitor_events(session, limit=limit)
