from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..dependencies import get_current_user
from ..models import User
from ..schemas import AccessPointResponse, OpenGateRequest, OpenGateResponse
from ..services import access as access_service
from ..services.gate import gate_client

router = APIRouter(prefix="/gate", tags=["gate"])


@router.get("/access-points", response_model=list[AccessPointResponse])
async def get_access_points() -> list[AccessPointResponse]:
    points = gate_client.get_access_points()
    return [AccessPointResponse(id=int(item["id"]), name=str(item["name"])) for item in points]


@router.post("/open", response_model=OpenGateResponse)
async def open_access_point(
    payload: OpenGateRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> OpenGateResponse:
    try:
        result = await access_service.open_access_point(session, user_id=user.id, access_point_id=payload.access_point_id)
    except access_service.AccessServiceError as exc:
        if exc.code in {"forbidden", "access_denied"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied") from exc
        if exc.code == "access_point_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access point not found") from exc
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc

    return OpenGateResponse(success=result.status == "success", message=result.message)
