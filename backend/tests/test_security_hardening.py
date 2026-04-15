from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.app.config import Settings
from backend.app.database import SessionLocal
from backend.app.models import User
from backend.app.security import LoginRateLimiter
from backend.app.services.user_accounts import set_user_password


async def _ensure_admin_user(login: str, password: str) -> None:
    async with SessionLocal() as session:
        query = await session.execute(select(User).where(User.login == login))
        user = query.scalar_one_or_none()
        if user is None:
            user = User(
                phone=f"+7999{str(uuid4().int)[:7]}",
                login=login,
                name="Security Admin",
                apartment="ADMIN",
                plot_number="ADMIN",
                is_admin=True,
                is_active=True,
            )
            session.add(user)
        else:
            user.is_admin = True
            user.is_active = True
        set_user_password(user, password, require_change=False)
        await session.commit()


def test_production_settings_reject_insecure_defaults():
    settings = Settings(
        _env_file=None,
        environment="production",
        secret_key="change-me",
        debug=False,
        docs_enabled=False,
        bootstrap_demo_user=False,
        bootstrap_test_users_json="[]",
    )

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        settings.validate_runtime_security()


def test_production_settings_require_strong_bootstrap_admin_password():
    settings = Settings(
        _env_file=None,
        environment="production",
        secret_key="test-secret-key-for-production-validation-12345",
        debug=False,
        docs_enabled=False,
        bootstrap_demo_user=False,
        bootstrap_test_users_json="[]",
        bootstrap_admin_user=True,
        admin_password="weakpass",
        cors_allow_origins_json='["https://example.com"]',
        allowed_hosts_json='["example.com"]',
        database_url="sqlite+aiosqlite:///./backend_prod.db",
    )

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        settings.validate_runtime_security()


def test_login_rate_limiter_can_reset_failures():
    limiter = LoginRateLimiter(attempts=2, window_seconds=60)

    assert limiter.is_allowed("resident")
    limiter.record_failure("resident")
    assert limiter.is_allowed("resident")
    limiter.record_failure("resident")
    assert not limiter.is_allowed("resident")

    limiter.reset("resident")
    assert limiter.is_allowed("resident")


def test_auth_responses_are_not_cacheable_and_send_hsts(client):
    response = client.post(
        "/auth/login",
        headers={"X-Forwarded-Proto": "https"},
        json={"login": "demo", "password": "demo123"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_admin_user_list_hides_password_after_resident_changes_it(client):
    admin_login = f"security_admin_{uuid4().hex[:6]}"
    admin_password = "StrongAdmin!91"
    asyncio.run(_ensure_admin_user(admin_login, admin_password))

    admin_token = client.post(
        "/api/auth/login",
        json={"login": admin_login, "password": admin_password},
    ).json()["access_token"]

    create_response = client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "full_name": "Petrov Petr",
            "phone": f"+7999{str(uuid4().int)[-7:]}",
            "plot_number": "915",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()

    resident_login = client.post(
        "/auth/login",
        json={"login": created["login"], "password": created["password"]},
    )
    assert resident_login.status_code == 200
    resident_token = resident_login.json()["access_token"]

    change_password = client.put(
        "/user/password",
        headers={"Authorization": f"Bearer {resident_token}"},
        json={"newPassword": "NewStrong!93", "repeatPassword": "NewStrong!93"},
    )
    assert change_password.status_code == 200

    list_response = client.get(
        f"/api/admin/users?search={created['login']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_response.status_code == 200
    listed = next(item for item in list_response.json()["items"] if item["login"] == created["login"])
    assert listed["password"] is None
    assert listed["password_change_required"] is False


def test_change_password_rejects_weak_password(client):
    phone_digits = f"9{str(uuid4().int)[-9:]}"
    resident_login = client.post(
        "/auth/register",
        json={
            "fullName": "Ivanov Ivan",
            "phoneNumber": f"+7 {phone_digits[:3]} {phone_digits[3:6]} {phone_digits[6:8]} {phone_digits[8:10]}",
            "plotNumber": "911",
        },
    ).json()

    resident_auth = client.post(
        "/auth/login",
        json={"login": resident_login["login"], "password": resident_login["password"]},
    )
    assert resident_auth.status_code == 200
    resident_token = resident_auth.json()["access_token"]

    weak_change = client.put(
        "/user/password",
        headers={"Authorization": f"Bearer {resident_token}"},
        json={"newPassword": "weakpass", "repeatPassword": "weakpass"},
    )
    assert weak_change.status_code == 422


def test_registration_rejects_same_phone_in_another_format(client):
    phone_digits = f"9{str(uuid4().int)[-9:]}"
    first = client.post(
        "/auth/register",
        json={
            "fullName": "Petrov Petr",
            "phoneNumber": f"+7 {phone_digits[:3]} {phone_digits[3:6]}-{phone_digits[6:8]}-{phone_digits[8:10]}",
            "plotNumber": "321",
        },
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/auth/register",
        json={
            "fullName": "Petrova Anna",
            "phoneNumber": f"8 ({phone_digits[:3]}) {phone_digits[3:6]}-{phone_digits[6:8]}-{phone_digits[8:10]}",
            "plotNumber": "322",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "phone_already_exists"
