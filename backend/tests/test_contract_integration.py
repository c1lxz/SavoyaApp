from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.models import User
from backend.app.services.auth import hash_password


def test_compat_login_success(client):
    response = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'})
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert data['user']['login'] == 'demo'
    assert isinstance(data['access_token'], str)


def test_compat_login_failure(client):
    response = client.post('/auth/login', json={'login': 'demo', 'password': 'wrong'})
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is False
    assert data['error'] == 'Invalid login or password'


def test_passes_create_and_list(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    create_response = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': 'A123BB',
            'plotNumber': '25',
            'expiresAt': None,
            'isPermanent': True,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['status'] == 'permanent'

    list_response = client.get('/passes/my', headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) >= 1
    assert any(item['carNumber'] == 'A123BB' for item in rows)


def test_temporary_pass_create_and_list_with_sqlite_datetimes(client):
    login_name = f'temp_{uuid4().hex[:8]}'
    password = 'demo123'
    asyncio.run(_ensure_user(login_name, password, full_name='Temp User', plot_number='25'))

    login = client.post('/auth/login', json={'login': login_name, 'password': password}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    expires_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    create_response = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': 'T555TT',
            'plotNumber': '25',
            'expiresAt': expires_at,
            'isPermanent': False,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['status'] == 'active'
    assert created['expiresAt'] is not None

    list_response = client.get('/passes/my', headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert any(item['carNumber'] == 'T555TT' for item in rows)


def test_gate_open_action(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    client.post(
        '/passes',
        headers=headers,
        json={'carNumber': 'B234CC', 'plotNumber': '25', 'expiresAt': None, 'isPermanent': True},
    )
    response = client.post('/gates/open-action', headers=headers, json={'action': 'entry'})
    assert response.status_code == 200
    data = response.json()
    assert data['action'] == 'entry'
    assert 'success' in data


async def _ensure_user_without_name(login: str, password: str) -> None:
    async with SessionLocal() as session:
        query = await session.execute(select(User).where(User.login == login))
        user = query.scalar_one_or_none()
        if user is None:
            session.add(
                User(
                    phone=f"+7999{str(uuid4().int)[:7]}",
                    login=login,
                    password_hash=hash_password(password),
                    name=None,
                    apartment='1',
                    plot_number='1',
                    is_admin=False,
                    is_active=True,
                )
            )
        else:
            user.password_hash = hash_password(password)
            user.name = None
            user.is_active = True
        await session.commit()


async def _ensure_user(login: str, password: str, *, full_name: str, plot_number: str) -> None:
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
                    is_admin=False,
                    is_active=True,
                )
            )
        else:
            user.password_hash = hash_password(password)
            user.name = full_name
            user.apartment = plot_number
            user.plot_number = plot_number
            user.is_active = True
        await session.commit()


def test_compat_login_requires_profile_completion_when_full_name_missing(client):
    login = f'profile_{uuid4().hex[:8]}'
    password = 'demo123'
    asyncio.run(_ensure_user_without_name(login, password))

    response = client.post('/auth/login', json={'login': login, 'password': password})
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert data['requiresProfileCompletion'] is True
    assert data['user']['fullName'] == ''


def test_compat_update_profile_persists_full_name(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    update = client.put('/user/profile', headers=headers, json={'fullName': 'Иванов Иван Иванович', 'plotNumber': '77'})
    assert update.status_code == 200
    body = update.json()
    assert body['fullName'] == 'Иванов Иван Иванович'
    assert body['plotNumber'] == '77'

    me = client.get('/user/me', headers=headers)
    assert me.status_code == 200
    me_body = me.json()
    assert me_body['fullName'] == 'Иванов Иван Иванович'
    assert me_body['plotNumber'] == '77'
