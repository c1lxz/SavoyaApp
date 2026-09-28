from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import secrets
from datetime import datetime
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext
from sqlalchemy import delete, func, inspect, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import AccessEventLog, AccessKey, AccessPermission, Log, Request, User
from ..news_models import NewsDevice, NewsMedia, NewsNotification, NewsPollVote, NewsPost
from .gate import gate_client
from ..utils.datetime import ensure_utc_datetime
from ..utils.input_safety import (
    normalize_account_phone,
    normalize_full_name,
    normalize_login,
    normalize_password,
    normalize_plot_number,
)

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)

_CYRILLIC_NAME_RE = re.compile(r"[^А-Яа-яЁё]+")
_PASSWORD_SPECIALS = "!@#$%&*+-_"
_PASSWORD_DIGITS = "0123456789"
_PASSWORD_RUSSIAN_LOWERCASE = (
    "\u0430\u0431\u0432\u0433\u0434\u0435\u0436\u0437\u0438\u0439\u043a\u043b\u043c\u043d\u043e\u043f"
    "\u0440\u0441\u0442\u0443\u0444\u0445\u0446\u0447\u0448\u0449\u044a\u044b\u044c\u044d\u044e\u044f"
)
_PASSWORD_RUSSIAN_UPPERCASE = _PASSWORD_RUSSIAN_LOWERCASE.upper()


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
    if require_change:
        user.password_change_prompt_shown = False


def _extract_login_surname(full_name: str) -> str:
    raw_surname = full_name.strip().split()[0]
    surname = _CYRILLIC_NAME_RE.sub("", raw_surname)
    if not surname:
        return "Житель"
    return f"{surname[:1].upper()}{surname[1:].lower()}"[:40]


def generate_password(length: int = 8) -> str:
    if length < 8:
        length = 8

    letter_count = max(0, length - 3)
    lowercase_count = max(0, letter_count - 1)
    password_chars = [
        *(secrets.choice(_PASSWORD_RUSSIAN_LOWERCASE) for _ in range(lowercase_count)),
        secrets.choice(_PASSWORD_RUSSIAN_UPPERCASE),
        secrets.choice(_PASSWORD_DIGITS),
        secrets.choice(_PASSWORD_DIGITS),
        secrets.choice(_PASSWORD_SPECIALS),
    ]

    while len(password_chars) < length:
        password_chars.append(secrets.choice(_PASSWORD_RUSSIAN_LOWERCASE))

    secrets.SystemRandom().shuffle(password_chars)
    return "".join(password_chars)


async def ensure_users_schema(session: AsyncSession) -> None:
    connection = await session.connection()

    def _get_columns(sync_connection) -> set[str]:
        return {str(column["name"]) for column in inspect(sync_connection).get_columns("users")}

    columns = await connection.run_sync(_get_columns)
    migration_statements = (
        ("staff_role", "ALTER TABLE users ADD COLUMN staff_role VARCHAR(24) NULL"),
        ("auth_generation", "ALTER TABLE users ADD COLUMN auth_generation VARCHAR(32) NULL"),
        ("login", "ALTER TABLE users ADD COLUMN login VARCHAR(100) NULL"),
        ("password_hash", "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL"),
        ("plot_number", "ALTER TABLE users ADD COLUMN plot_number VARCHAR(20) NULL"),
        ("owner_index", "ALTER TABLE users ADD COLUMN owner_index INTEGER NULL"),
        ("password_encrypted", "ALTER TABLE users ADD COLUMN password_encrypted TEXT NULL"),
        ("password_change_required", "ALTER TABLE users ADD COLUMN password_change_required BOOLEAN NOT NULL DEFAULT 0"),
        (
            "password_change_prompt_shown",
            "ALTER TABLE users ADD COLUMN password_change_prompt_shown BOOLEAN NOT NULL DEFAULT 0",
        ),
    )

    for column_name, statement in migration_statements:
        if column_name in columns:
            continue
        await session.execute(text(statement))
        await session.commit()

    # Backfill only legacy administrators. Re-running startup must preserve
    # explicitly assigned dispatcher roles and must never promote residents.
    await session.execute(
        update(User).where(User.is_admin.is_(True), User.staff_role.is_(None))
        .values(staff_role="administration").execution_options(synchronize_session=False)
    )
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


def should_show_password_change_prompt(user: User) -> bool:
    return bool(user.password_change_required and not user.password_change_prompt_shown)


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
    plot_number: str | None,
    require_password_change: bool = True,
    staff_role: str | None = None,
) -> tuple[User, str]:
    if staff_role not in {None, "administration", "dispatcher"}:
        raise UserAccountError(code="invalid_staff_role", message="Неизвестная роль сотрудника")
    normalized_name = _validate_full_name_words(full_name)
    normalized_phone = normalize_account_phone(phone_number)
    normalized_plot = normalize_plot_number(plot_number) if plot_number is not None else None
    if staff_role is None and normalized_plot is None:
        raise UserAccountError(code="plot_required", message="Для жителя укажите номер участка")

    existing_user_id = await _find_existing_user_id_by_phone(session, normalized_phone)
    if existing_user_id is not None:
        raise UserAccountError(code="phone_already_exists", message="Пользователь с таким номером уже существует")

    if staff_role is None:
        owner_index = await _next_owner_index(session, normalized_plot)
        login = await _generate_login(session, full_name=normalized_name, plot_number=normalized_plot, owner_index=owner_index)
    else:
        owner_index = None
        surname = _extract_login_surname(normalized_name)
        base_login = normalize_login(f"{'д' if staff_role == 'dispatcher' else 'а'}{surname}")
        login = base_login
        suffix = 2
        while await session.scalar(select(User.id).where(User.login == login)) is not None:
            login = normalize_login(f"{base_login}{suffix}")
            suffix += 1
    password = generate_password()

    user = User(
        phone=normalized_phone,
        name=normalized_name,
        apartment=normalized_plot,
        plot_number=normalized_plot,
        login=login,
        owner_index=owner_index,
        is_admin=staff_role is not None,
        staff_role=staff_role,
        auth_generation=uuid4().hex,
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


def build_admin_user_payload(
    user: User,
    *,
    visible_password_override: str | None = None,
) -> dict[str, str | int | bool | None | datetime]:
    visible_password = visible_password_override
    if visible_password is None and user.password_change_required:
        visible_password = decrypt_visible_password(user.password_encrypted)
    return {
        "id": user.id,
        "login": str(user.login or ""),
        "password": visible_password,
        "full_name": user.name,
        "phone": user.phone,
        "plot_number": user.plot_number or user.apartment,
        "owner_index": user.owner_index,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "staff_role": user.effective_staff_role,
        "password_change_required": user.password_change_required,
        "created_at": ensure_utc_datetime(user.created_at),
    }


async def delete_user_account(
    session: AsyncSession,
    *,
    user: User,
    strict_gate_cleanup: bool = True,
) -> None:
    request_rows = await session.execute(select(Request.gate_key_id).where(Request.resident_id == user.id))
    key_rows = await session.execute(select(AccessKey.id, AccessKey.external_id).where(AccessKey.user_id == user.id))

    gate_key_ids: set[int] = set()
    access_key_ids: list[int] = []
    for access_key_id, external_id in key_rows.all():
        access_key_ids.append(int(access_key_id))
        if external_id is not None:
            try:
                numeric_id = int(str(external_id).strip())
            except (TypeError, ValueError):
                continue
            if numeric_id > 0:
                gate_key_ids.add(numeric_id)

    for raw_value in [*request_rows.scalars().all(), user.gate_user_id]:
        if raw_value is None:
            continue
        try:
            numeric_id = int(str(raw_value).strip())
        except (TypeError, ValueError):
            continue
        if numeric_id > 0:
            gate_key_ids.add(numeric_id)

    for gate_key_id in sorted(gate_key_ids):
        try:
            await asyncio.to_thread(gate_client.remove_key, gate_key_id)
        except Exception as exc:
            if strict_gate_cleanup:
                raise UserAccountError(
                    code="gate_cleanup_failed",
                    message=f"Не удалось удалить пропуск Gate {gate_key_id}: {exc}",
                ) from exc
            logger.exception("Failed to revoke gate key during user deletion", extra={"user_id": user.id, "gate_key_id": gate_key_id})

    access_event_filter = AccessEventLog.user_id == user.id
    access_permission_filter = AccessPermission.user_id == user.id
    if access_key_ids:
        access_event_filter = or_(access_event_filter, AccessEventLog.key_id.in_(access_key_ids))
        access_permission_filter = or_(access_permission_filter, AccessPermission.key_id.in_(access_key_ids))

    await session.execute(delete(AccessEventLog).where(access_event_filter))
    await session.execute(delete(AccessPermission).where(access_permission_filter))
    await session.execute(delete(AccessKey).where(AccessKey.user_id == user.id))
    await session.execute(delete(Request).where(Request.resident_id == user.id))
    await session.execute(update(Log).where(Log.user_id == user.id).values(user_id=None))
    # Older SQLite installations run with foreign keys disabled. Reproduce the
    # declared cascades explicitly, so a reused user/device ID cannot inherit a
    # deleted account's poll votes or pending push notifications.
    device_ids = select(NewsDevice.id).where(NewsDevice.user_id == user.id)
    await session.execute(delete(NewsNotification).where(NewsNotification.device_id.in_(device_ids)))
    await session.execute(delete(NewsDevice).where(NewsDevice.user_id == user.id))
    await session.execute(delete(NewsPollVote).where(NewsPollVote.user_id == user.id))
    await session.execute(update(NewsPost).where(NewsPost.author_id == user.id).values(author_id=None))
    await session.execute(update(NewsMedia).where(NewsMedia.owner_id == user.id).values(owner_id=None))
    await session.delete(user)
    await session.commit()
