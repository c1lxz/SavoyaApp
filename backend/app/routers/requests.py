from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..dependencies import get_current_user
from ..models import User
from ..schemas import CreateRequestRequest, RequestResponse
from ..services import requests as request_service

router = APIRouter(prefix="/requests", tags=["requests"])


def _to_response(item) -> RequestResponse:
    return RequestResponse(
        id=item.id,
        resident_id=item.resident_id,
        key_type=item.key_type,
        key_value=item.key_value,
        is_permanent=item.is_permanent,
        expires_at=item.expires_at,
        status=item.status,
        created_at=item.created_at,
    )


@router.post("/", response_model=RequestResponse)
async def create_request(
    payload: CreateRequestRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> RequestResponse:
    if not payload.is_permanent and payload.hours is None:
        payload.hours = 24
    try:
        request = await request_service.create_request(session, user, payload)
    except request_service.RequestConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except request_service.RequestIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return _to_response(request)


@router.get("/", response_model=list[RequestResponse])
async def list_requests(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[RequestResponse]:
    rows = await request_service.list_my_requests(session, user.id)
    return [_to_response(item) for item in rows]


@router.delete("/{request_id}", response_model=RequestResponse)
async def cancel_request(
    request_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> RequestResponse:
    row = await request_service.cancel_request(session, user.id, request_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    return _to_response(row)
