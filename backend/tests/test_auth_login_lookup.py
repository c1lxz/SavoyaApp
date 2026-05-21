"""Login lookup must tolerate the mobile-keyboard / Cyrillic-vs-Latin pitfalls
that generated logins (e.g. ``с1Житель305``) hit in practice.

Generated logins start with the Cyrillic letter ``с``, which is visually
indistinguishable from the Latin ``c``.  Mobile keyboards also autocapitalize
the first character of an input field.  Either of those silently breaks a
case-sensitive exact-match lookup against ``User.login`` and surfaces as
"Invalid login or password" even when the credentials are correct.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.models import User
from backend.app.services.auth import (
    _canonical_login_form,
    hash_password,
    login_with_password,
)


# ---------------------------------------------------------------------------
# _canonical_login_form — pure helper, no DB needed
# ---------------------------------------------------------------------------


def test_canonical_login_form_lowercases_input():
    assert _canonical_login_form("С1Житель305") == _canonical_login_form("с1житель305")


def test_canonical_login_form_collapses_latin_to_cyrillic_lookalikes():
    # Stored Cyrillic "с1Житель305" must collide with typed Latin "c1Житель305".
    stored = _canonical_login_form("с1Житель305")
    typed_latin = _canonical_login_form("c1Житель305")
    assert stored == typed_latin


def test_canonical_login_form_handles_mobile_autocapitalize():
    # Mobile autocapitalize turns "с" into "С"; canonical form must match.
    assert _canonical_login_form("С1Житель305") == _canonical_login_form("с1Житель305")


def test_canonical_login_form_preserves_non_lookalike_characters():
    # Latin lowercase "b" has no Cyrillic look-alike — it must survive untouched
    # so that, e.g., a uuid hex suffix "abc123" still compares equal between
    # typed (latin) and stored (latin) representations.
    assert _canonical_login_form("c1Тестabc123") == _canonical_login_form("с1Тестabc123")


# ---------------------------------------------------------------------------
# login_with_password — integration with the DB
# ---------------------------------------------------------------------------


def _seed_user(login: str, password: str) -> None:
    async def _do() -> None:
        async with SessionLocal() as session:
            query = await session.execute(select(User).where(User.login == login))
            existing = query.scalar_one_or_none()
            if existing is not None:
                await session.delete(existing)
                await session.commit()
            session.add(
                User(
                    phone=f"+7999{str(uuid4().int)[:7]}",
                    login=login,
                    password_hash=hash_password(password),
                    name="Login Probe",
                    apartment="500",
                    plot_number="500",
                    is_admin=False,
                    is_active=True,
                )
            )
            await session.commit()

    asyncio.run(_do())


def _try_login(login: str, password: str):
    async def _do():
        async with SessionLocal() as session:
            return await login_with_password(session, login, password)

    return asyncio.run(_do())


def test_login_with_password_accepts_exact_cyrillic_login():
    stored_login = f"с1Тест{uuid4().hex[:6]}"
    _seed_user(stored_login, "secret-pwd")
    user, token, error = _try_login(stored_login, "secret-pwd")
    assert error is None
    assert token is not None
    assert user is not None and user.login == stored_login


def test_login_with_password_accepts_latin_lookalike_for_cyrillic_login():
    """User typed Latin "c" — stored login starts with Cyrillic "с"."""
    stored_login = f"с1Тест{uuid4().hex[:6]}"
    _seed_user(stored_login, "secret-pwd")
    # Replace leading Cyrillic "с" (U+0441) with Latin "c" (U+0063).
    typed_login = "c" + stored_login[1:]
    assert typed_login != stored_login
    user, token, error = _try_login(typed_login, "secret-pwd")
    assert error is None, f"expected login to succeed via look-alike, got {error!r}"
    assert token is not None
    assert user is not None and user.login == stored_login


def test_login_with_password_is_case_insensitive():
    """Mobile autocapitalize uppercases the first char; stored login is lowercase prefix."""
    stored_login = f"с1тест{uuid4().hex[:6]}"
    _seed_user(stored_login, "secret-pwd")
    user, token, error = _try_login(stored_login.upper(), "secret-pwd")
    assert error is None, f"expected case-insensitive match, got {error!r}"
    assert token is not None
    assert user is not None and user.login == stored_login


def test_login_with_password_still_rejects_wrong_password():
    stored_login = f"с1Тест{uuid4().hex[:6]}"
    _seed_user(stored_login, "right-pwd")
    user, token, error = _try_login(stored_login, "wrong-pwd")
    assert user is None
    assert token is None
    assert error == "invalid_credentials"


def test_login_with_password_still_rejects_unknown_login():
    user, token, error = _try_login(f"nosuch_{uuid4().hex}", "irrelevant")
    assert user is None
    assert token is None
    assert error == "invalid_credentials"
