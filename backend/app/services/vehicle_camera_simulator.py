from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import AccessPoint, Request
from ..utils.datetime import ensure_utc_datetime, utcnow
from ..utils.input_safety import normalize_vehicle_number
from ..utils.vehicle_number import compact_vehicle_number
from . import access as access_service
from .gate import gate_client

settings = get_settings()
_DEFAULT_ACTION = "entry"


class VehicleCameraSimulationError(Exception):
    pass


@dataclass
class VehicleCameraSimulationResult:
    vehicle_number: str
    access_point_id: int
    access_point_name: str | None
    allowed_access_point_ids: list[int]
    external_key_id: str
    backend_request_id: int | None
    backend_gate_key_id: int | None
    open_success: bool
    open_message: str
    open_error_code: str | None = None
    open_details: dict[str, Any] | None = None
    simulated_camera_event: dict[str, Any] | None = None
    simulated_camera_event_processed: bool = False
    courier_scheduled_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_access_point_ids(values: Iterable[int] | None) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for raw_value in values or []:
        point_id = int(raw_value)
        if point_id <= 0 or point_id in seen:
            continue
        seen.add(point_id)
        normalized.append(point_id)
    return normalized


def _request_is_current(request_item: Request, now: datetime) -> bool:
    if request_item.status != "active":
        return False
    if request_item.is_permanent:
        return True
    expires_at = ensure_utc_datetime(request_item.expires_at)
    if expires_at is None:
        return True
    return expires_at >= now


def _canonical_vehicle_number(value: str) -> str:
    return compact_vehicle_number(normalize_vehicle_number(value))


async def _find_active_vehicle_request(session: AsyncSession, normalized_vehicle_number: str) -> Request | None:
    query = await session.execute(
        select(Request)
        .where(
            Request.key_type == "VehicleNumber",
            Request.status == "active",
        )
        .order_by(Request.id.desc())
    )
    now = utcnow()
    lookup_key = _canonical_vehicle_number(normalized_vehicle_number)
    rows = [
        row
        for row in query.scalars().all()
        if _request_is_current(row, now) and compact_vehicle_number(row.key_value) == lookup_key
    ]
    if not rows:
        return None
    rows.sort(
        key=lambda item: (
            0 if item.gate_key_id is not None and int(item.gate_key_id) > 0 else 1,
            -int(item.id),
        )
    )
    return rows[0]


def resolve_target_access_point(
    *,
    access_point_id: int | None = None,
    action: str | None = None,
    allowed_access_point_ids: Iterable[int] | None = None,
) -> int:
    allowed_ids = _normalize_access_point_ids(allowed_access_point_ids)
    if access_point_id is not None:
        resolved = int(access_point_id)
        if resolved <= 0:
            raise VehicleCameraSimulationError("access_point_id must be a positive integer")
    else:
        resolved_action = (action or _DEFAULT_ACTION).strip().lower()
        resolved = settings.gate_action_map.get(resolved_action, 0)
        if resolved <= 0:
            known_actions = ", ".join(sorted(settings.gate_action_map))
            raise VehicleCameraSimulationError(
                f"Unknown action '{resolved_action}'. Available actions: {known_actions}"
            )

    if allowed_ids and resolved not in allowed_ids:
        raise VehicleCameraSimulationError(
            f"Access point {resolved} is not allowed for this vehicle. Allowed ids: {allowed_ids}"
        )
    return resolved


def build_simulated_gate_pass_event(
    *,
    access_point_id: int,
    user_ptr: int,
    key_value: str,
    access_point_name: str | None = None,
    event_time: datetime | None = None,
    event_index: int | None = None,
) -> dict[str, Any]:
    normalized_time = ensure_utc_datetime(event_time) or utcnow()
    resolved_index = int(event_index) if event_index is not None else int(normalized_time.timestamp() * 1000)
    return {
        "index": resolved_index,
        "time": normalized_time.isoformat(),
        "event_type": 1,
        "event_code": 2,
        "access_point_id": int(access_point_id),
        "unit": str(access_point_name or f"Access point {access_point_id}"),
        "message": "Simulated camera recognition by vehicle number",
        "name": str(key_value),
        "user_ptr": int(user_ptr),
    }


async def simulate_vehicle_camera_open(
    session: AsyncSession,
    *,
    vehicle_number: str,
    access_point_id: int | None = None,
    action: str | None = None,
    simulate_camera_event: bool = True,
) -> VehicleCameraSimulationResult:
    normalized_vehicle_number = normalize_vehicle_number(vehicle_number)
    request_item = await _find_active_vehicle_request(session, normalized_vehicle_number)

    allowed_access_point_ids: list[int] = []
    backend_gate_key_id: int | None = None
    external_key_id = normalized_vehicle_number
    warnings: list[str] = []

    if request_item is not None:
        allowed_access_point_ids = _normalize_access_point_ids(request_item.access_point_ids or [])
        if request_item.gate_key_id is not None and int(request_item.gate_key_id) > 0:
            backend_gate_key_id = int(request_item.gate_key_id)
            external_key_id = str(backend_gate_key_id)
        else:
            warnings.append(
                "Active backend request has no gate_key_id. Falling back to vehicle-number lookup in Gate."
            )

    if not allowed_access_point_ids:
        permissions = gate_client.get_key_permissions(normalized_vehicle_number)
        allowed_access_point_ids = _normalize_access_point_ids(
            item.get("access_point_id")
            for item in permissions
            if isinstance(item, dict) and item.get("access_point_id") is not None
        )
        if not allowed_access_point_ids:
            raise VehicleCameraSimulationError(
                f"Vehicle {normalized_vehicle_number} was not found in active backend passes or Gate permissions."
            )
        warnings.append(
            "Vehicle permissions were resolved directly from Gate. Backend camera-event simulation may be unavailable."
        )

    await access_service.sync_access_points(session)
    resolved_access_point_id = resolve_target_access_point(
        access_point_id=access_point_id,
        action=action,
        allowed_access_point_ids=allowed_access_point_ids,
    )

    access_point = await session.get(AccessPoint, resolved_access_point_id)
    access_point_name = access_point.name if access_point is not None else None

    open_result = gate_client.open_access_point(
        resolved_access_point_id,
        key_external_id=external_key_id,
    )

    simulated_event: dict[str, Any] | None = None
    simulated_camera_event_processed = False
    courier_scheduled_count = 0

    if simulate_camera_event:
        if not open_result.success:
            warnings.append("Physical open failed, so backend camera-event simulation was skipped.")
        elif request_item is None or backend_gate_key_id is None:
            warnings.append(
                "Backend camera-event simulation requires an active backend vehicle pass with gate_key_id."
            )
        else:
            simulated_event = build_simulated_gate_pass_event(
                access_point_id=resolved_access_point_id,
                user_ptr=backend_gate_key_id,
                key_value=normalized_vehicle_number,
                access_point_name=access_point_name,
            )
            courier_scheduled_count = await access_service.process_courier_gate_entry_events(
                session,
                [simulated_event],
            )
            simulated_camera_event_processed = True

    return VehicleCameraSimulationResult(
        vehicle_number=normalized_vehicle_number,
        access_point_id=resolved_access_point_id,
        access_point_name=access_point_name,
        allowed_access_point_ids=allowed_access_point_ids,
        external_key_id=external_key_id,
        backend_request_id=int(request_item.id) if request_item is not None else None,
        backend_gate_key_id=backend_gate_key_id,
        open_success=bool(open_result.success),
        open_message=str(open_result.message),
        open_error_code=str(open_result.code) if open_result.code else None,
        open_details=dict(open_result.details or {}) or None,
        simulated_camera_event=simulated_event,
        simulated_camera_event_processed=simulated_camera_event_processed,
        courier_scheduled_count=courier_scheduled_count,
        warnings=warnings,
    )
