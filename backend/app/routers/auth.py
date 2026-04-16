from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..dependencies import get_current_user
from ..models import User
from ..schemas import LoginRequest, MessageResponse, TokenResponse, UserResponse
from ..services.auth import consume_password_change_prompt, login_with_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user_response(user: User, *, password_change_prompt_required: bool = False) -> UserResponse:
    return UserResponse(
        id=user.id,
        phone=user.phone,
        name=user.name,
        apartment=user.apartment,
        is_admin=user.is_admin,
        password_change_required=user.password_change_required,
        password_change_prompt_required=password_change_prompt_required,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, session: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    client_ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.login_rate_limiter
    ip_limiter = request.app.state.login_ip_rate_limiter
    rate_limit_key = f"api:{client_ip}:{payload.login.lower()}"
    ip_rate_limit_key = f"api:{client_ip}"
    if not limiter.is_allowed(rate_limit_key) or not ip_limiter.is_allowed(ip_rate_limit_key):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")

    user, token, error_code = await login_with_password(session, payload.login, payload.password)
    if user is None or token is None:
        limiter.record_failure(rate_limit_key)
        ip_limiter.record_failure(ip_rate_limit_key)
    else:
        limiter.reset(rate_limit_key)
    if error_code == "inactive_user":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Пользователь деактивирован")
    if user is None or token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")
    should_prompt = await consume_password_change_prompt(session, user)
    return TokenResponse(access_token=token, user=_to_user_response(user, password_change_prompt_required=should_prompt))


@router.post("/logout", response_model=MessageResponse)
async def logout(_user: User = Depends(get_current_user)) -> MessageResponse:
    return MessageResponse(message="Сессия завершена")
