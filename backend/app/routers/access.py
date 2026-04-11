from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..dependencies import get_current_user
from ..models import User
from ..schemas import AccessEventItem, AccessPointMyResponse, OpenAccessRequest, OpenAccessResponse
from ..services import access as access_service

router = APIRouter(prefix="/access", tags=["access"])
legacy_router = APIRouter(tags=["access"])


async def _list_my_access_points_impl(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[AccessPointMyResponse]:
    points = await access_service.list_my_access_points(session, user_id=user.id)
    return [
        AccessPointMyResponse(
            id=point.id,
            name=point.name,
            code=point.code,
            type=point.type,
        )
        for point in points
    ]


@router.get("/points/my", response_model=list[AccessPointMyResponse])
@router.get("/access-points/my", response_model=list[AccessPointMyResponse], include_in_schema=False)
async def list_my_access_points(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[AccessPointMyResponse]:
    return await _list_my_access_points_impl(session=session, user=user)


@legacy_router.get("/access-points/my", response_model=list[AccessPointMyResponse], include_in_schema=False)
async def list_my_access_points_legacy(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[AccessPointMyResponse]:
    return await _list_my_access_points_impl(session=session, user=user)


@router.post("/open", response_model=OpenAccessResponse)
async def open_access_point(
    payload: OpenAccessRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> OpenAccessResponse:
    try:
        result = await access_service.open_access_point(
            session,
            user_id=user.id,
            access_point_id=payload.access_point_id,
        )
    except access_service.AccessServiceError as exc:
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc

    return OpenAccessResponse(
        status=result.status,
        message=result.message,
        request_id=result.request_id,
    )


@router.get("/events/my", response_model=list[AccessEventItem])
async def list_my_access_events(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[AccessEventItem]:
    rows = await access_service.list_my_access_events(session, user_id=user.id)
    return [
        AccessEventItem(
            request_id=row.request_id,
            access_point_id=row.access_point_id,
            status=row.status,
            action=row.action,
            error_code=row.error_code,
            error_message=row.error_message,
            details=row.details,
            created_at=row.created_at,
        )
        for row in rows
    ]
