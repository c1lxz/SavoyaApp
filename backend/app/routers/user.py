from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..dependencies import get_current_user
from ..models import Log, User
from ..schemas import UserResponse

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=user.id,
        phone=user.phone,
        name=user.name,
        apartment=user.apartment,
        is_admin=user.is_admin,
    )


@router.get("/logs")
async def get_my_logs(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[dict]:
    query = await session.execute(select(Log).where(Log.user_id == user.id).order_by(Log.created_at.desc()).limit(100))
    rows = list(query.scalars().all())
    return [
        {
            "id": row.id,
            "action": row.action,
            "access_point_id": row.access_point_id,
            "success": row.success,
            "error_message": row.error_message,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]

