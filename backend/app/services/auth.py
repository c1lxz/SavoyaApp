from __future__ import annotations

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import User
from ..utils.jwt import create_access_token

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


async def ensure_demo_user(session: AsyncSession) -> None:
    query = await session.execute(select(User).where(User.login == settings.demo_login))
    user = query.scalar_one_or_none()
    if user is not None:
        return

    demo = User(
        phone=settings.demo_phone,
        name=settings.demo_full_name,
        apartment=settings.demo_plot_number,
        is_admin=False,
        is_active=True,
        login=settings.demo_login,
        password_hash=hash_password(settings.demo_password),
        plot_number=settings.demo_plot_number,
    )
    session.add(demo)
    await session.commit()


async def login_with_password(session: AsyncSession, login: str, password: str) -> tuple[User | None, str | None, str | None]:
    query = await session.execute(select(User).where(User.login == login))
    user = query.scalar_one_or_none()
    if user is None or not user.password_hash:
        return None, None, "invalid_credentials"

    if not verify_password(password, user.password_hash):
        return None, None, "invalid_credentials"

    if not user.is_active:
        return None, None, "inactive_user"

    token = create_access_token(subject=str(user.id))
    return user, token, None
