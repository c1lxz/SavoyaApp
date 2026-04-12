from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.models import User
from backend.app.services.auth import hash_password


async def _ensure_user(
    login: str,
    password: str,
    *,
    full_name: str,
    plot_number: str,
    is_admin: bool = False,
) -> None:
    async with SessionLocal() as session:
        query = await session.execute(select(User).where(User.login == login))
        user = query.scalar_one_or_none()
        if user is None:
            session.add(
                User(
                    phone=f"+7999{str(uuid4().int)[:7]}",
                    login=login,
                    password_hash=hash_password(password),
                    name=full_name,
                    apartment=plot_number,
                    plot_number=plot_number,
                    is_admin=is_admin,
                    is_active=True,
                )
            )
        else:
            user.password_hash = hash_password(password)
            user.name = full_name
            user.apartment = plot_number
            user.plot_number = plot_number
            user.is_admin = is_admin
            user.is_active = True
        await session.commit()


def _api_login(client, login: str, password: str) -> str:
    response = client.post('/api/auth/login', json={'login': login, 'password': password})
    assert response.status_code == 200
    return response.json()['access_token']


def test_admin_requests_endpoint_rejects_non_admin_user(client):
    token = _api_login(client, 'demo', 'demo123')
    response = client.get('/api/admin/requests', headers={'Authorization': f'Bearer {token}'})

    assert response.status_code == 403
    assert response.json()['detail'] == 'Admin access required'


def test_admin_requests_endpoint_returns_requests_from_multiple_users(client):
    admin_login = f'admin_{uuid4().hex[:8]}'
    user_a = f'user_a_{uuid4().hex[:6]}'
    user_b = f'user_b_{uuid4().hex[:6]}'
    password = 'demo123'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin User', plot_number='900', is_admin=True))
    asyncio.run(_ensure_user(user_a, password, full_name='Resident Alpha', plot_number='101'))
    asyncio.run(_ensure_user(user_b, password, full_name='Resident Beta', plot_number='202'))

    token_a = _api_login(client, user_a, password)
    token_b = _api_login(client, user_b, password)

    first_create = client.post(
        '/passes',
        headers={'Authorization': f'Bearer {token_a}'},
        json={
            'carNumber': 'A123BC77',
            'plotNumber': '101',
            'phoneNumber': None,
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )
    second_create = client.post(
        '/passes',
        headers={'Authorization': f'Bearer {token_b}'},
        json={
            'carNumber': '123ABC01',
            'plotNumber': '202',
            'phoneNumber': None,
            'expiresAt': (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
            'isPermanent': False,
            'isCourier': False,
        },
    )

    assert first_create.status_code == 200
    assert second_create.status_code == 200

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/requests', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 2
    assert len(body['items']) == 2

    by_login = {item['resident']['login']: item for item in body['items']}
    assert by_login[user_a]['resident']['full_name'] == 'Resident Alpha'
    assert by_login[user_a]['country_label'] == 'Россия'
    assert by_login[user_b]['resident']['full_name'] == 'Resident Beta'
    assert by_login[user_b]['country_label'] == 'Казахстан'
    assert 'password_hash' not in by_login[user_a]['resident']


def test_admin_requests_endpoint_supports_filters(client):
    admin_login = f'admin_filter_{uuid4().hex[:6]}'
    resident_login = f'resident_{uuid4().hex[:6]}'
    password = 'demo123'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Filter', plot_number='901', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Filter', plot_number='303'))

    resident_token = _api_login(client, resident_login, password)
    create_response = client.post(
        '/passes',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={
            'carNumber': '123ABC01',
            'plotNumber': '303',
            'phoneNumber': '+77010000033',
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200

    admin_token = _api_login(client, admin_login, password)
    response = client.get(
        '/api/admin/requests?search=123ABC01&status=permanent&key_type=VehicleNumber',
        headers={'Authorization': f'Bearer {admin_token}'},
    )

    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 1
    assert body['items'][0]['key_value'] == '123ABC01'
    assert body['items'][0]['status'] == 'permanent'


def test_api_login_rate_limit_returns_429_after_repeated_failures(client):
    for attempt in range(5):
        response = client.post('/api/auth/login', json={'login': 'demo', 'password': f'wrong-{attempt}'})
        assert response.status_code == 401

    blocked = client.post('/api/auth/login', json={'login': 'demo', 'password': 'still-wrong'})
    assert blocked.status_code == 429
    assert blocked.json()['detail'] == 'Too many login attempts'


def test_compat_login_rate_limit_returns_error_after_repeated_failures(client):
    for attempt in range(5):
        response = client.post('/auth/login', json={'login': 'demo', 'password': f'wrong-{attempt}'})
        assert response.status_code == 200
        assert response.json()['success'] is False

    blocked = client.post('/auth/login', json={'login': 'demo', 'password': 'still-wrong'})
    assert blocked.status_code == 200
    assert blocked.json()['success'] is False
    assert blocked.json()['error'] == 'Too many login attempts'
