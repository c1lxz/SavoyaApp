from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..dependencies import get_current_admin_user
from ..models import Request, User
from ..schemas import AdminRequestItem, AdminRequestListResponse, AdminResidentSummary
from ..services.requests import list_requests_for_admin, resolve_request_status
from ..utils.vehicle_country import detect_vehicle_country

router = APIRouter(prefix="/admin", tags=["admin"])


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
        expires_at=item.expires_at,
        status=resolve_request_status(item.is_permanent, item.expires_at) if item.status == "active" else item.status,
        created_at=item.created_at,
        cancelled_at=item.cancelled_at,
        plot_number=item.plot_number,
    )


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
