from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db_session
from ..dependencies import get_current_user
from ..models import User
from ..schemas import (
    CompatAuthResult,
    CompatCreatePassPayload,
    CompatGateActionResult,
    CompatLoginPayload,
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
from ..services.requests import (
    RequestConflictError,
    RequestIntegrationError,
    cancel_request as cancel_created_request,
    create_request,
    list_my_requests,
    resolve_request_status,
)
from ..utils.datetime import to_utc_isoformat, utcnow

router = APIRouter(tags=["compatibility"])
settings = get_settings()


_INVALID_LOGIN_MESSAGE = "Invalid login or password"
_PHONE_READER_HINTS = (
    "gsm",
    "gate terminal",
    "terminal",
    "phone",
    "call",
    "caller",
    "telephone",
    "звон",
    "вызов",
    "телефон",
)


def _compat_user(user: User) -> CompatUser:
    return CompatUser(
        id=str(user.id),
        login=user.login or "",
        fullName=user.name or "",
        plotNumber=user.plot_number or user.apartment or "",
        phoneNumber=user.phone or "",
        isAdmin=user.is_admin,
    )


def _infer_action_from_access_point_name(name: str) -> str | None:
    value = (name or "").lower()
    if "въезд" in value or "entry" in value:
        return "entry"
    if "выезд" in value or "exit" in value:
        return "exit"
    if "север" in value or "north" in value:
        return "wicket_north"
    if "калитка 1" in value or "admin" in value or "админ" in value or "администрац" in value:
        return "wicket_admin"
    if "озер" in value or "lake" in value:
        return "wicket_lake"
    if "лес" in value or "forest" in value:
        return "wicket_forest"
    return None


def _runtime_gate_action_map() -> dict[str, int]:
    configured = dict(settings.gate_action_map)
    if not settings.gate_real_integration_enabled:
        return configured

    points = gate_client.get_access_points()
    available_ids = {int(item["id"]) for item in points}
    resolved = {action: point_id for action, point_id in configured.items() if point_id in available_ids}
    for point in points:
        action = _infer_action_from_access_point_name(str(point["name"]))
        if action and action not in resolved:
            resolved[action] = int(point["id"])
    return resolved or configured


def _runtime_default_access_point_ids() -> list[int]:
    configured = list(settings.default_access_point_ids)
    if not settings.gate_real_integration_enabled:
        return configured

    points = gate_client.get_access_points()
    available_ids = {int(item["id"]) for item in points}
    if configured and all(point_id in available_ids for point_id in configured):
        return configured
    return [int(item["id"]) for item in points] or configured


def _looks_like_phone_reader(name: str) -> bool:
    value = (name or "").strip().lower()
    return any(hint in value for hint in _PHONE_READER_HINTS)


def _runtime_gsm_access_point_ids() -> list[int]:
    configured = list(settings.gsm_access_point_ids)
    if not settings.gate_real_integration_enabled:
        return configured

    points = gate_client.get_access_points()
    available_ids = {int(item["id"]) for item in points}
    configured_ids: list[int] = []
    seen: set[int] = set()
    for point_id in configured:
        if point_id not in available_ids or point_id in seen:
            continue
        seen.add(point_id)
        configured_ids.append(point_id)
    if configured_ids:
        return configured_ids

    gsm_ids: list[int] = []
    for item in points:
        point_id = int(item["id"])
        if point_id in seen:
            continue
        if _looks_like_phone_reader(str(item["name"] or "")):
            seen.add(point_id)
            gsm_ids.append(point_id)
    return gsm_ids


def _merge_access_point_ids(*groups: list[int]) -> list[int]:
    merged: list[int] = []
    seen: set[int] = set()
    for group in groups:
        for point_id in group:
            if point_id in seen:
                continue
            seen.add(point_id)
            merged.append(point_id)
    return merged


def _build_compat_create_payloads(payload: CompatCreatePassPayload) -> list[CreateRequestRequest]:
    hours: int | None = None
    if not payload.isPermanent and payload.expiresAt:
        try:
            expires_at = datetime.fromisoformat(payload.expiresAt.replace("Z", "+00:00"))
            diff = expires_at - datetime.now(timezone.utc)
            hours = max(1, int(diff.total_seconds() // 3600))
        except ValueError:
            hours = 24

    default_access_point_ids = _runtime_default_access_point_ids()
    phone_access_point_ids = _runtime_gsm_access_point_ids() or default_access_point_ids

    requests: list[CreateRequestRequest] = []
    if payload.carNumber:
        requests.append(
            CreateRequestRequest(
                key_type="VehicleNumber",
                key_value=payload.carNumber,
                phone_number=payload.phoneNumber,
                access_point_ids=default_access_point_ids,
                is_permanent=payload.isPermanent,
                is_courier=payload.isCourier,
                hours=None if payload.isPermanent else (hours or 24),
                plot_number=payload.plotNumber,
            )
        )
    if payload.phoneNumber:
        requests.append(
            CreateRequestRequest(
                key_type="Phone",
                key_value=payload.phoneNumber,
                phone_number=payload.phoneNumber,
                access_point_ids=phone_access_point_ids,
                is_permanent=payload.isPermanent,
                is_courier=payload.isCourier,
                hours=None if payload.isPermanent else (hours or 24),
                plot_number=payload.plotNumber,
            )
        )

    return requests


@router.post("/auth/login", response_model=CompatAuthResult)
async def compat_login(
    payload: CompatLoginPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> CompatAuthResult:
    client_ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.login_rate_limiter
    if not limiter.is_allowed(f"compat:{client_ip}:{payload.login.lower()}"):
        return CompatAuthResult(success=False, error="Too many login attempts")

    user, token, error_code = await login_with_password(session, payload.login, payload.password)
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
    user.name = payload.fullName
    if payload.plotNumber is not None:
        user.plot_number = payload.plotNumber
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _compat_user(user)


def _to_compat_pass(item) -> CompatPassItem:
    status = resolve_request_status(item.is_permanent, item.expires_at)
    expires = to_utc_isoformat(item.expires_at)
    created = to_utc_isoformat(item.created_at) or utcnow().isoformat()
    key_type = str(item.key_type or "VehicleNumber")
    key_value = str(item.key_value or "")
    return CompatPassItem(
        id=str(item.id),
        keyType=key_type,
        keyValue=key_value,
        carNumber=key_value if key_type == "VehicleNumber" else None,
        plotNumber=item.plot_number or "",
        phoneNumber=key_value if key_type == "Phone" else item.contact_phone,
        expiresAt=expires,
        isPermanent=item.is_permanent,
        isCourier=bool(getattr(item, "is_courier", False)),
        status=status,
        createdAt=created,
    )


@router.post("/passes", response_model=CompatPassItem)
async def compat_create_pass(
    payload: CompatCreatePassPayload,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> CompatPassItem:
    create_payloads = _build_compat_create_payloads(payload)
    if not create_payloads:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "missing_pass_identifier", "message": "Provide either car number or phone number"},
        )

    created_requests = []
    try:
        for create_payload in create_payloads:
            created_requests.append(await create_request(session, user, create_payload))
    except RequestConflictError as exc:
        for created in reversed(created_requests):
            await cancel_created_request(session, user.id, created.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except RequestIntegrationError as exc:
        for created in reversed(created_requests):
            await cancel_created_request(session, user.id, created.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return _to_compat_pass(created_requests[0])


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
    access_point_id = _runtime_gate_action_map().get(payload.action)
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
