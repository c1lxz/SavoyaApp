from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..dependencies import get_current_user
from ..models import User
from ..schemas import LoginRequest, MessageResponse, TokenResponse, UserResponse
from ..services.auth import login_with_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        phone=user.phone,
        name=user.name,
        apartment=user.apartment,
        is_admin=user.is_admin,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    user, token, error_code = await login_with_password(session, payload.login, payload.password)
    if error_code == "inactive_user":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Пользователь деактивирован")
    if user is None or token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")
    return TokenResponse(access_token=token, user=_to_user_response(user))


@router.post("/logout", response_model=MessageResponse)
async def logout(_user: User = Depends(get_current_user)) -> MessageResponse:
    return MessageResponse(message="Сессия завершена")
