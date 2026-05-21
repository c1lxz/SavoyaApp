from __future__ import annotations

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import User
from ..utils.jwt import create_access_token
from ..utils.input_safety import normalize_account_phone
from .user_accounts import set_user_password, should_show_password_change_prompt

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()

# Generated logins mix Cyrillic prefix (``с``), Cyrillic surnames and digits.
# Mobile keyboards autocapitalize the first character, and Latin look-alike
# letters (``c``/``С``, ``a``/``А`` …) are visually indistinguishable from
# their Cyrillic counterparts.  Both issues silently break a case-sensitive
# exact-match lookup on ``User.login``.  ``_login_lookup_candidates`` produces
# the small set of equivalence-class variants worth probing on the server so
# the user can sign in without having to fight their keyboard.
_LATIN_TO_CYRILLIC_LOOKALIKES = str.maketrans(
    {
        "A": "А", "a": "а",
        "B": "В",
        "C": "С", "c": "с",
        "E": "Е", "e": "е",
        "H": "Н",
        "K": "К", "k": "к",
        "M": "М",
        "O": "О", "o": "о",
        "P": "Р", "p": "р",
        "T": "Т",
        "X": "Х", "x": "х",
        "Y": "У", "y": "у",
    }
)


def _canonical_login_form(login: str) -> str:
    """Reduce *login* to a single canonical form for case-insensitive,
    Cyrillic/Latin-look-alike-tolerant comparison.

    Every confusable Latin letter is mapped to its Cyrillic counterpart and
    the result is casefolded.  Comparing two values by this form matches when
    they differ only in case or in interchangeable look-alike letters.
    """
    return login.translate(_LATIN_TO_CYRILLIC_LOOKALIKES).casefold()


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

    user.phone = normalize_account_phone(settings.demo_phone)
    user.name = settings.demo_full_name
    user.apartment = settings.demo_plot_number
    user.is_admin = False
    user.is_active = True
    user.login = settings.demo_login
    user.plot_number = settings.demo_plot_number
    user.owner_index = 1
    set_user_password(user, settings.demo_password, require_change=False)
    await session.commit()


async def ensure_admin_user(session: AsyncSession) -> None:
    if not settings.bootstrap_admin_user:
        return
    if not settings.admin_login.strip() or not settings.admin_password.strip():
        return

    query = await session.execute(select(User).where(User.login == settings.admin_login))
    user = query.scalar_one_or_none()
    if user is None:
        user = User(login=settings.admin_login)
        session.add(user)

    user.phone = normalize_account_phone(settings.admin_phone)
    user.name = settings.admin_full_name
    user.apartment = settings.admin_plot_number
    user.is_admin = True
    user.is_active = True
    user.login = settings.admin_login
    user.plot_number = settings.admin_plot_number
    user.owner_index = None
    set_user_password(user, settings.admin_password, require_change=False)
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

        user.phone = normalize_account_phone(payload["phone"])
        user.name = payload["name"] or f"Test User {payload['login']}"
        user.apartment = payload["plot_number"] or None
        user.is_admin = False
        user.is_active = True
        user.login = payload["login"]
        user.plot_number = payload["plot_number"] or None
        user.owner_index = user.owner_index or 1
        set_user_password(user, payload["password"], require_change=False)

    await session.commit()


async def login_with_password(session: AsyncSession, login: str, password: str) -> tuple[User | None, str | None, str | None]:
    # Fast path: stored login matches the typed input character-for-character.
    query = await session.execute(select(User).where(User.login == login))
    matched_users: list[User] = [u for u in query.scalars().all() if u.password_hash]

    if not matched_users:
        # Slow path: tolerate mobile autocapitalize + Cyrillic/Latin look-alikes.
        # SQLite's LOWER() is ASCII-only, so the comparison has to happen in
        # Python.  User counts on this deployment are small (hundreds at most),
        # so a single scan is acceptable for the failure case.
        target_canonical = _canonical_login_form(login)
        scan = await session.execute(
            select(User).where(User.password_hash.is_not(None), User.login.is_not(None))
        )
        matched_users = [
            candidate
            for candidate in scan.scalars().all()
            if _canonical_login_form(candidate.login or "") == target_canonical
        ]

    if not matched_users:
        return None, None, "invalid_credentials"

    # If several rows share a casefold collision, prefer active users and the one
    # whose password actually verifies.
    matched_users.sort(key=lambda candidate: (not candidate.is_active, candidate.id))
    verified = next(
        (candidate for candidate in matched_users if verify_password(password, candidate.password_hash)),
        None,
    )
    if verified is None:
        return None, None, "invalid_credentials"

    if not verified.is_active:
        return None, None, "inactive_user"

    token = create_access_token(subject=str(verified.id))
    return verified, token, None


async def consume_password_change_prompt(session: AsyncSession, user: User) -> bool:
    should_prompt = should_show_password_change_prompt(user)
    if not should_prompt:
        return False

    user.password_change_prompt_shown = True
    session.add(user)
    await session.commit()
    return True
