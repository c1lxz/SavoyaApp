from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import User
from ..utils.input_safety import (
    normalize_account_phone,
    normalize_full_name,
    normalize_login,
    normalize_password,
    normalize_plot_number,
)

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_CYRILLIC_NAME_RE = re.compile(r"[^А-Яа-яЁё]+")
_PASSWORD_SPECIALS = "!@#$%&*+-_"
_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789" + _PASSWORD_SPECIALS


class UserAccountError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _build_fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_visible_password(password: str) -> str:
    return _build_fernet().encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_visible_password(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None

    try:
        return _build_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def set_user_password(user: User, password: str, *, require_change: bool) -> None:
    normalized = normalize_password(password)
    user.password_hash = pwd_context.hash(normalized)
    user.password_encrypted = encrypt_visible_password(normalized) if require_change else None
    user.password_change_required = require_change


def _extract_login_surname(full_name: str) -> str:
    raw_surname = full_name.strip().split()[0]
    surname = _CYRILLIC_NAME_RE.sub("", raw_surname)
    if not surname:
        return "Житель"
    return f"{surname[:1].upper()}{surname[1:].lower()}"[:40]


def generate_password(length: int = 12) -> str:
    if length < 10:
        length = 10

    while True:
        password = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(ch.islower() for ch in password)
            and any(ch.isupper() for ch in password)
            and any(ch.isdigit() for ch in password)
            and any(ch in _PASSWORD_SPECIALS for ch in password)
        ):
            return password


async def ensure_users_schema(session: AsyncSession) -> None:
    connection = await session.connection()

    def _get_columns(sync_connection) -> set[str]:
        return {str(column["name"]) for column in inspect(sync_connection).get_columns("users")}

    columns = await connection.run_sync(_get_columns)
    migration_statements = (
        ("login", "ALTER TABLE users ADD COLUMN login VARCHAR(100) NULL"),
        ("password_hash", "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL"),
        ("plot_number", "ALTER TABLE users ADD COLUMN plot_number VARCHAR(20) NULL"),
        ("owner_index", "ALTER TABLE users ADD COLUMN owner_index INTEGER NULL"),
        ("password_encrypted", "ALTER TABLE users ADD COLUMN password_encrypted TEXT NULL"),
        ("password_change_required", "ALTER TABLE users ADD COLUMN password_change_required BOOLEAN NOT NULL DEFAULT 0"),
    )

    for column_name, statement in migration_statements:
        if column_name in columns:
            continue
        await session.execute(text(statement))
        await session.commit()

    await clear_stale_visible_passwords(session)


async def clear_stale_visible_passwords(session: AsyncSession) -> int:
    result = await session.execute(
        text(
            """
            UPDATE users
            SET password_encrypted = NULL
            WHERE password_change_required = 0
              AND password_encrypted IS NOT NULL
            """
        )
    )
    await session.commit()
    return int(result.rowcount or 0)


def _validate_full_name_words(full_name: str) -> str:
    normalized = normalize_full_name(full_name)
    if len([part for part in normalized.split(" ") if part]) < 2:
        raise UserAccountError(code="invalid_full_name", message="Укажите фамилию и имя")
    return normalized


async def _next_owner_index(session: AsyncSession, plot_number: str) -> int:
    query = await session.execute(
        select(func.max(User.owner_index)).where(
            User.is_admin.is_(False),
            User.plot_number == plot_number,
        )
    )
    current = query.scalar_one_or_none()
    return int(current or 0) + 1


async def _generate_login(session: AsyncSession, *, full_name: str, plot_number: str, owner_index: int) -> str:
    surname = _extract_login_surname(full_name)
    base_login = normalize_login(f"с{owner_index}{surname}{plot_number}")

    query = await session.execute(select(User.id).where(User.login == base_login))
    if query.scalar_one_or_none() is None:
        return base_login

    suffix = 2
    while True:
        candidate = normalize_login(f"{base_login}{suffix}")
        query = await session.execute(select(User.id).where(User.login == candidate))
        if query.scalar_one_or_none() is None:
            return candidate
        suffix += 1


async def _find_existing_user_id_by_phone(session: AsyncSession, normalized_phone: str) -> int | None:
    query = await session.execute(select(User.id, User.phone).where(User.phone.is_not(None)))
    for raw_user_id, raw_phone in query.all():
        if raw_phone is None:
            continue
        try:
            candidate_phone = normalize_account_phone(str(raw_phone))
        except ValueError:
            continue
        if candidate_phone == normalized_phone:
            return int(raw_user_id)
    return None


async def create_user_account(
    session: AsyncSession,
    *,
    full_name: str,
    phone_number: str,
    plot_number: str,
    require_password_change: bool = True,
) -> tuple[User, str]:
    normalized_name = _validate_full_name_words(full_name)
    normalized_phone = normalize_account_phone(phone_number)
    normalized_plot = normalize_plot_number(plot_number)

    existing_user_id = await _find_existing_user_id_by_phone(session, normalized_phone)
    if existing_user_id is not None:
        raise UserAccountError(code="phone_already_exists", message="Пользователь с таким номером уже существует")

    owner_index = await _next_owner_index(session, normalized_plot)
    login = await _generate_login(session, full_name=normalized_name, plot_number=normalized_plot, owner_index=owner_index)
    password = generate_password()

    user = User(
        phone=normalized_phone,
        name=normalized_name,
        apartment=normalized_plot,
        plot_number=normalized_plot,
        login=login,
        owner_index=owner_index,
        is_admin=False,
        is_active=True,
    )
    set_user_password(user, password, require_change=require_password_change)

    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, password


async def update_user_password(session: AsyncSession, *, user: User, new_password: str) -> User:
    set_user_password(user, new_password, require_change=False)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def build_admin_user_payload(user: User) -> dict[str, str | int | bool | None | datetime]:
    visible_password = decrypt_visible_password(user.password_encrypted) if user.password_change_required else None
    return {
        "id": user.id,
        "login": user.login,
        "password": visible_password,
        "full_name": user.name,
        "phone": user.phone,
        "plot_number": user.plot_number or user.apartment,
        "owner_index": user.owner_index,
        "is_active": user.is_active,
        "password_change_required": user.password_change_required,
        "created_at": user.created_at,
    }
