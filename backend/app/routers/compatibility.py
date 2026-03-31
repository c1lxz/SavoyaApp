from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db_session
from ..dependencies import get_current_user
from ..models import User
from ..schemas import (
    CompatAuthResult,
    CompatCreatePassPayload,
    CompatGateActionResult,
    CompatOpenActionRequest,
    CompatPassItem,
    CompatUpdateProfilePayload,
    CompatUser,
    CreateRequestRequest,
    MessageResponse,
)
from ..services import access as access_service
from ..services.auth import login_with_password
from ..services.gate import gate_client
from ..services.requests import create_request, list_my_requests, resolve_request_status

router = APIRouter(tags=["compatibility"])
settings = get_settings()


_INVALID_LOGIN_MESSAGE = "Invalid login or password"


def _compat_user(user: User) -> CompatUser:
    return CompatUser(
        id=str(user.id),
        login=user.login or "",
        fullName=user.name or "",
        plotNumber=user.plot_number or user.apartment or "",
    )


@router.post("/auth/login", response_model=CompatAuthResult)
async def compat_login(payload: dict, session: AsyncSession = Depends(get_db_session)) -> CompatAuthResult:
    login = str(payload.get("login", "")).strip()
    password = str(payload.get("password", ""))
    if not login or not password:
        return CompatAuthResult(success=False, error=_INVALID_LOGIN_MESSAGE)

    user, token, error_code = await login_with_password(session, login, password)
    if error_code == "inactive_user":
        return CompatAuthResult(success=False, error="User is inactive")
    if user is None or token is None:
        return CompatAuthResult(success=False, error=_INVALID_LOGIN_MESSAGE)

    return CompatAuthResult(
        success=True,
        user=_compat_user(user),
        access_token=token,
        requiresProfileCompletion=not bool((user.name or "").strip()),
    )


@router.get("/user/me", response_model=CompatUser)
async def compat_get_me(user: User = Depends(get_current_user)) -> CompatUser:
    return _compat_user(user)


@router.put("/user/profile", response_model=CompatUser)
async def compat_update_profile(
    payload: CompatUpdateProfilePayload,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> CompatUser:
    normalized_name = payload.fullName.strip()
    if not normalized_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Full name is required")

    user.name = normalized_name
    if payload.plotNumber is not None:
        user.plot_number = payload.plotNumber.strip()
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _compat_user(user)


def _to_compat_pass(item) -> CompatPassItem:
    status = resolve_request_status(item.is_permanent, item.expires_at)
    expires = item.expires_at.astimezone(timezone.utc).isoformat() if item.expires_at else None
    created = item.created_at.astimezone(timezone.utc).isoformat() if item.created_at else datetime.now(timezone.utc).isoformat()
    return CompatPassItem(
        id=str(item.id),
        carNumber=item.key_value,
        plotNumber=item.plot_number or "",
        expiresAt=expires,
        isPermanent=item.is_permanent,
        status=status,
        createdAt=created,
    )


@router.post("/passes", response_model=CompatPassItem)
async def compat_create_pass(
    payload: CompatCreatePassPayload,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> CompatPassItem:
    hours: int | None = None
    if not payload.isPermanent and payload.expiresAt:
        try:
            expires_at = datetime.fromisoformat(payload.expiresAt.replace("Z", "+00:00"))
            diff = expires_at - datetime.now(timezone.utc)
            hours = max(1, int(diff.total_seconds() // 3600))
        except ValueError:
            hours = 24

    create_payload = CreateRequestRequest(
        key_type="VehicleNumber",
        key_value=payload.carNumber.strip().upper(),
        access_point_ids=settings.default_access_point_ids,
        is_permanent=payload.isPermanent,
        hours=None if payload.isPermanent else (hours or 24),
        plot_number=payload.plotNumber,
    )
    request = await create_request(session, user, create_payload)
    return _to_compat_pass(request)


@router.get("/passes/my", response_model=list[CompatPassItem])
async def compat_list_passes(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[CompatPassItem]:
    rows = await list_my_requests(session, user.id)
    visible = [row for row in rows if row.status in {"active", "expired"}]
    return [_to_compat_pass(item) for item in visible]


@router.delete("/passes/{pass_id}", response_model=MessageResponse)
async def compat_cancel_pass(
    pass_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> MessageResponse:
    from ..services.requests import cancel_request

    try:
        numeric_id = int(pass_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pass id") from exc

    row = await cancel_request(session, user.id, numeric_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pass not found")
    return MessageResponse(message="Pass cancelled")


@router.post("/gates/open-action", response_model=CompatGateActionResult)
async def compat_open_gate_action(
    payload: CompatOpenActionRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> CompatGateActionResult:
    access_point_id = settings.gate_action_map.get(payload.action)
    if access_point_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown action")

    try:
        result = await access_service.open_access_point(session, user_id=user.id, access_point_id=access_point_id)
        return CompatGateActionResult(
            success=result.status == "success",
            action=payload.action,
            message=result.message,
            timestamp=gate_client.now_unix_ms(),
        )
    except access_service.AccessServiceError as exc:
        return CompatGateActionResult(
            success=False,
            action=payload.action,
            message=exc.message,
            timestamp=gate_client.now_unix_ms(),
        )
