from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.models import Request, User
from backend.app.services.auth import hash_password
from backend.app.services.gate import gate_client
from backend.app.services.user_accounts import create_user_account


def test_compat_login_success(client):
    response = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'})
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert data['user']['login'] == 'demo'
    assert 'phoneNumber' in data['user']
    assert isinstance(data['access_token'], str)


def test_compat_login_failure(client):
    response = client.post('/auth/login', json={'login': 'demo', 'password': 'wrong'})
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is False
    assert data['error'] == 'Invalid login or password'


async def _create_admin_managed_resident(full_name: str, phone_number: str, plot_number: str) -> tuple[str, str]:
    async with SessionLocal() as session:
        user, password = await create_user_account(
            session,
            full_name=full_name,
            phone_number=phone_number,
            plot_number=plot_number,
            require_password_change=True,
        )
        return user.login or "", password


def test_compat_register_account_endpoint_is_removed(client):
    response = client.post(
        '/auth/register',
        json={
            'fullName': 'Иванов Иван',
            'phoneNumber': f"+7999{str(uuid4().int)[-7:]}",
            'plotNumber': '47',
        },
    )

    assert response.status_code in {404, 405}


def test_compat_change_password_updates_login_credentials(client):
    plot_number = str(800 + (uuid4().int % 150))
    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    login, password = asyncio.run(_create_admin_managed_resident('Sidorov Sidor', phone_number, plot_number))

    login_response = client.post(
        '/auth/login',
        json={'login': login, 'password': password},
    )
    assert login_response.status_code == 200
    login_body = login_response.json()
    assert login_body['success'] is True

    token = login_body['access_token']
    new_password = 'Strong!Pass91'
    password_response = client.put(
        '/user/password',
        headers={'Authorization': f'Bearer {token}'},
        json={'newPassword': new_password, 'repeatPassword': new_password},
    )

    assert password_response.status_code == 200
    assert password_response.json()['passwordChangeRequired'] is False

    old_login_response = client.post(
        '/auth/login',
        json={'login': login, 'password': password},
    )
    assert old_login_response.status_code == 200
    assert old_login_response.json()['success'] is False

    new_login_response = client.post(
        '/auth/login',
        json={'login': login, 'password': new_password},
    )
    assert new_login_response.status_code == 200
    new_login_body = new_login_response.json()
    assert new_login_body['success'] is True
    assert new_login_body['passwordChangeRequired'] is False


def test_compat_password_change_prompt_is_shown_only_on_first_login(client):
    plot_number = str(900 + (uuid4().int % 90))
    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    login, password = asyncio.run(_create_admin_managed_resident('Petrov Petr', phone_number, plot_number))

    first_login = client.post(
        '/auth/login',
        json={'login': login, 'password': password},
    )
    assert first_login.status_code == 200
    first_login_body = first_login.json()
    assert first_login_body['success'] is True
    assert first_login_body['user']['passwordChangeRequired'] is True
    assert first_login_body['user']['passwordChangePromptRequired'] is True

    me_response = client.get(
        '/user/me',
        headers={'Authorization': f"Bearer {first_login_body['access_token']}"},
    )
    assert me_response.status_code == 200
    me_body = me_response.json()
    assert me_body['passwordChangeRequired'] is True
    assert me_body['passwordChangePromptRequired'] is False

    second_login = client.post(
        '/auth/login',
        json={'login': login, 'password': password},
    )
    assert second_login.status_code == 200
    second_login_body = second_login.json()
    assert second_login_body['success'] is True
    assert second_login_body['user']['passwordChangeRequired'] is True
    assert second_login_body['user']['passwordChangePromptRequired'] is False


def test_passes_create_and_list(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    car_number = f'A{uuid4().hex[:5]}'.upper()

    create_response = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': car_number,
            'plotNumber': '25',
            'phoneNumber': '+79991234567',
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['status'] == 'permanent'
    assert created['phoneNumber'] == '+79991234567'

    list_response = client.get('/passes/my', headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) >= 1
    assert any(item['carNumber'] == car_number for item in rows)


def test_passes_create_normalizes_cyrillic_vehicle_number_to_ascii(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    create_response = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': 'А123СХ 77',
            'plotNumber': '25',
            'phoneNumber': '+79991234567',
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['carNumber'] == 'A123CX 77'

    async def _latest_request_key_value() -> str:
        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(User.id).where(User.login == 'demo')
                )
            ).scalar_one()
            request_row = (
                await session.execute(
                    select(Request)
                    .where(Request.resident_id == row, Request.key_type == 'VehicleNumber')
                    .order_by(Request.id.desc())
                    .limit(1)
                )
            ).scalar_one()
            return str(request_row.key_value)

    assert asyncio.run(_latest_request_key_value()) == 'A123CX 77'


def test_temporary_pass_create_and_list_with_sqlite_datetimes(client):
    login_name = f'temp_{uuid4().hex[:8]}'
    password = 'demo123'
    asyncio.run(_ensure_user(login_name, password, full_name='Temp User', plot_number='25'))

    login = client.post('/auth/login', json={'login': login_name, 'password': password}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    expires_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    car_number = f'T{uuid4().hex[:5]}'.upper()

    create_response = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': car_number,
            'plotNumber': '25',
            'phoneNumber': '+79997654321',
            'expiresAt': expires_at,
            'isPermanent': False,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['status'] == 'active'
    assert created['expiresAt'] is not None
    assert created['phoneNumber'] == '+79997654321'

    list_response = client.get('/passes/my', headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert any(item['carNumber'] == car_number for item in rows)


def test_temporary_pass_create_preserves_exact_expiry_time(client):
    login_name = f'exact_expiry_{uuid4().hex[:8]}'
    password = 'demo123'
    asyncio.run(_ensure_user(login_name, password, full_name='Exact Expiry User', plot_number='26'))

    login = client.post('/auth/login', json={'login': login_name, 'password': password}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    requested_expires_at = (datetime.now(timezone.utc) + timedelta(hours=7, minutes=35)).replace(microsecond=0)

    create_response = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': f'E{uuid4().hex[:5]}'.upper(),
            'plotNumber': '26',
            'phoneNumber': '+79998887766',
            'expiresAt': requested_expires_at.isoformat(),
            'isPermanent': False,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    created_expires_at = datetime.fromisoformat(created['expiresAt'].replace('Z', '+00:00'))

    assert abs(created_expires_at - requested_expires_at) <= timedelta(minutes=1)


def test_passes_create_uses_account_phone_when_phone_number_is_omitted(client):
    login_name = f'account_phone_{uuid4().hex[:8]}'
    password = 'demo123'
    asyncio.run(_ensure_user(login_name, password, full_name='Account Phone User', plot_number='31'))

    login = client.post('/auth/login', json={'login': login_name, 'password': password}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    account_phone = login['user']['phoneNumber']
    car_number = f'Z{uuid4().hex[:5]}'.upper()

    create_response = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': car_number,
            'plotNumber': '31',
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['keyType'] == 'VehicleNumber'
    assert created['phoneNumber'] == account_phone

    list_response = client.get('/passes/my', headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) == 1
    assert rows[0]['keyType'] == 'VehicleNumber'
    assert rows[0]['keyValue'] == car_number
    assert rows[0]['phoneNumber'] == account_phone


def test_passes_create_keeps_vehicle_request_only_when_phone_number_is_provided(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    car_number = f'K{uuid4().hex[:5]}'.upper()
    phone_number = '79991230011'

    create_response = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': car_number,
            'plotNumber': '25',
            'phoneNumber': phone_number,
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['keyType'] == 'VehicleNumber'
    assert created['keyValue'] == car_number

    list_response = client.get('/passes/my', headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) == 1
    assert rows[0]['keyType'] == 'VehicleNumber'
    assert rows[0]['keyValue'] == car_number
    assert rows[0]['phoneNumber'] == phone_number


def test_passes_create_rejects_duplicate_active_car_number(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    car_number = f'X{uuid4().hex[:5]}'.upper()

    first = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': car_number,
            'plotNumber': '25',
            'phoneNumber': '+79990000001',
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )
    assert first.status_code == 200

    second = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': car_number,
            'plotNumber': '25',
            'phoneNumber': '+79990000002',
            'expiresAt': (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            'isPermanent': False,
            'isCourier': False,
        },
    )
    assert second.status_code == 409
    assert second.json()['detail']['code'] == 'duplicate_request'


def test_gate_open_action(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}

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


async def _ensure_admin_user(login: str, password: str, *, full_name: str) -> None:
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
                    apartment="ADMIN",
                    plot_number="ADMIN",
                    is_admin=True,
                    is_active=True,
                )
            )
        else:
            user.password_hash = hash_password(password)
            user.name = full_name
            user.apartment = "ADMIN"
            user.plot_number = "ADMIN"
            user.is_admin = True
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


def test_compat_admin_login_and_me_keep_admin_flag(client):
    login = f"admin_{uuid4().hex[:8]}"
    password = "demo123"
    asyncio.run(_ensure_admin_user(login, password, full_name="Admin User"))

    response = client.post("/auth/login", json={"login": login, "password": password})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["user"]["isAdmin"] is True
    assert body["requiresProfileCompletion"] is False

    token = body["access_token"]
    me = client.get("/user/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["isAdmin"] is True


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


def test_passes_create_returns_502_when_gate_returns_invalid_key_id(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    original_add_permanent_key = gate_client.add_permanent_key
    gate_client.add_permanent_key = lambda **kwargs: 0
    try:
        response = client.post(
            '/passes',
            headers=headers,
            json={
                'carNumber': f'F{uuid4().hex[:5]}'.upper(),
                'plotNumber': '25',
                'phoneNumber': '+79995554433',
                'expiresAt': None,
                'isPermanent': True,
                'isCourier': False,
            },
        )
    finally:
        gate_client.add_permanent_key = original_add_permanent_key

    assert response.status_code == 502
    assert response.json()['detail']['code'] == 'invalid_gate_key'


def test_passes_create_returns_502_when_gate_bridge_raises(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    original_add_permanent_key = gate_client.add_permanent_key

    def _raise_gate_error(**kwargs):
        raise RuntimeError('Gate bridge failed with exit code 1')

    gate_client.add_permanent_key = _raise_gate_error
    try:
        response = client.post(
            '/passes',
            headers=headers,
            json={
                'carNumber': f'G{uuid4().hex[:5]}'.upper(),
                'plotNumber': '25',
                'phoneNumber': '+79995550011',
                'expiresAt': None,
                'isPermanent': True,
                'isCourier': False,
            },
        )
    finally:
        gate_client.add_permanent_key = original_add_permanent_key

    assert response.status_code == 502
    assert response.json()['detail']['code'] == 'gate_bridge_error'
    assert response.json()['detail']['message'] == 'Gate integration failed'


def test_passes_create_courier_flow_sets_flag(client):
    login = client.post('/auth/login', json={'login': 'demo', 'password': 'demo123'}).json()
    token = login['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    response = client.post(
        '/passes',
        headers=headers,
        json={
            'carNumber': f'C{uuid4().hex[:5]}'.upper(),
            'plotNumber': '25',
            'phoneNumber': '+79994443322',
            'expiresAt': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            'isPermanent': False,
            'isCourier': True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body['isCourier'] is True
    assert body['isPermanent'] is False
