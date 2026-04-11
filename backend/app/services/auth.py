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
    if not settings.bootstrap_demo_user:
        return

    query = await session.execute(select(User).where(User.login == settings.demo_login))
    user = query.scalar_one_or_none()
    if user is None:
        user = User(login=settings.demo_login)
        session.add(user)

    user.phone = settings.demo_phone
    user.name = settings.demo_full_name
    user.apartment = settings.demo_plot_number
    user.is_admin = False
    user.is_active = True
    user.login = settings.demo_login
    user.password_hash = hash_password(settings.demo_password)
    user.plot_number = settings.demo_plot_number
    await session.commit()


async def ensure_bootstrap_test_users(session: AsyncSession) -> None:
    bootstrap_users = settings.bootstrap_test_users
    if not bootstrap_users:
        return

    for payload in bootstrap_users:
        query = await session.execute(select(User).where(User.login == payload["login"]))
        user = query.scalar_one_or_none()
        if user is None:
            user = User(login=payload["login"])
            session.add(user)

        user.phone = payload["phone"]
        user.name = payload["name"] or f"Test User {payload['login']}"
        user.apartment = payload["plot_number"] or None
        user.is_admin = False
        user.is_active = True
        user.login = payload["login"]
        user.password_hash = hash_password(payload["password"])
        user.plot_number = payload["plot_number"] or None

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
