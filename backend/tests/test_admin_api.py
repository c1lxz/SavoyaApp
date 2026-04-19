from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.config import get_settings
from backend.app.messages import BLOCKED_ACCOUNT_MESSAGE
from backend.app.models import AccessEventLog, AccessKey, AccessPermission, AccessPoint, Log, Request, User
from backend.app.services.auth import hash_password
from backend.app.services.gate import GateOpenResult


def _is_strong_temporary_password(value: str) -> bool:
    return (
        len(value) >= 10
        and any(char.islower() for char in value)
        and any(char.isupper() for char in value)
        and any(char.isdigit() for char in value)
        and any(not char.isalnum() for char in value)
    )


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


async def _attach_user_deletion_dependencies(user_id: int) -> dict[str, int]:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.gate_user_id = 88005

        access_point = AccessPoint(
            name="Delete Test Gate",
            code=f"delete-test-{uuid4().hex}",
            type="gate",
            is_active=True,
        )
        session.add(access_point)
        await session.flush()

        request = Request(
            resident_id=user_id,
            key_type="VehicleNumber",
            key_value=f"D{uuid4().hex[:5]}",
            gate_key_id=88004,
            access_point_ids=[access_point.id],
            is_permanent=True,
            status="active",
        )
        access_key = AccessKey(
            user_id=user_id,
            external_id="88003",
            protocol_type="VehicleNumber",
            card_number=f"{uuid4().int % 100000}",
            is_active=True,
        )
        session.add_all([request, access_key])
        await session.flush()

        permission = AccessPermission(
            user_id=user_id,
            access_point_id=access_point.id,
            key_id=access_key.id,
            is_allowed=True,
        )
        event = AccessEventLog(
            user_id=user_id,
            access_point_id=access_point.id,
            key_id=access_key.id,
            request_id=f"delete-test-{uuid4().hex}",
            status="success",
        )
        log = Log(user_id=user_id, action="delete-test", success=True)
        session.add_all([permission, event, log])
        await session.commit()

        return {
            "access_event_id": event.id,
            "access_key_id": access_key.id,
            "access_permission_id": permission.id,
            "log_id": log.id,
            "request_id": request.id,
        }


async def _load_user_deletion_state(user_id: int, dependency_ids: dict[str, int]) -> dict[str, bool | int | str | None]:
    async with SessionLocal() as session:
        log = await session.get(Log, dependency_ids["log_id"])
        return {
            "user_exists": await session.get(User, user_id) is not None,
            "request_exists": await session.get(Request, dependency_ids["request_id"]) is not None,
            "access_key_exists": await session.get(AccessKey, dependency_ids["access_key_id"]) is not None,
            "access_permission_exists": await session.get(
                AccessPermission,
                dependency_ids["access_permission_id"],
            )
            is not None,
            "access_event_exists": await session.get(AccessEventLog, dependency_ids["access_event_id"]) is not None,
            "log_user_id": log.user_id if log is not None else "missing",
        }


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


def test_admin_users_crud_flow(client):
    admin_login = f'admin_users_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Users', plot_number='950', is_admin=True))

    admin_token = _api_login(client, admin_login, admin_password)
    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    plot_number = str(200000 + (uuid4().int % 700000))

    create_response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Сидоров Сидор',
            'phone': phone_number,
            'plot_number': plot_number,
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created['login'] == f'с1Сидоров{plot_number}'
    assert created['phone'] == phone_number
    assert created['plot_number'] == plot_number
    assert created['password']
    assert _is_strong_temporary_password(created['password'])
    assert created['password_change_required'] is True
    assert created['is_active'] is True

    user_id = created['id']
    user_login = created['login']
    user_password = created['password']

    list_response = client.get(
        f'/api/admin/users?search={user_login}',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert list_body['total'] >= 1
    listed = next(item for item in list_body['items'] if item['id'] == user_id)
    assert listed['password'] == user_password
    assert listed['full_name'] == 'Сидоров Сидор'

    block_response = client.post(
        f'/api/admin/users/{user_id}/block',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert block_response.status_code == 200
    assert block_response.json()['is_active'] is False

    blocked_login = client.post('/auth/login', json={'login': user_login, 'password': user_password})
    assert blocked_login.status_code == 200
    assert blocked_login.json()['success'] is False
    assert blocked_login.json()['error'] == BLOCKED_ACCOUNT_MESSAGE

    unblock_response = client.post(
        f'/api/admin/users/{user_id}/unblock',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert unblock_response.status_code == 200
    assert unblock_response.json()['is_active'] is True

    restored_login = client.post('/auth/login', json={'login': user_login, 'password': user_password})
    assert restored_login.status_code == 200
    assert restored_login.json()['success'] is True

    delete_response = client.delete(
        f'/api/admin/users/{user_id}',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert delete_response.status_code == 200

    after_delete = client.get(
        f'/api/admin/users?search={user_login}',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert after_delete.status_code == 200
    assert not any(item['id'] == user_id for item in after_delete.json()['items'])


def test_admin_can_delete_blocked_user_without_unblock(client):
    admin_login = f'admin_delete_blocked_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Delete Blocked', plot_number='955', is_admin=True))

    admin_token = _api_login(client, admin_login, admin_password)
    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    plot_number = str(210000 + (uuid4().int % 700000))

    create_response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Блоков Борис',
            'phone': phone_number,
            'plot_number': plot_number,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    user_id = created['id']
    user_login = created['login']

    block_response = client.post(
        f'/api/admin/users/{user_id}/block',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert block_response.status_code == 200
    assert block_response.json()['is_active'] is False

    delete_response = client.delete(
        f'/api/admin/users/{user_id}',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert delete_response.status_code == 200

    after_delete = client.get(
        f'/api/admin/users?search={user_login}',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert after_delete.status_code == 200
    assert not any(item['id'] == user_id for item in after_delete.json()['items'])


def test_admin_delete_user_removes_related_access_records(client, monkeypatch):
    admin_login = f'admin_delete_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Delete', plot_number='951', is_admin=True))

    admin_token = _api_login(client, admin_login, admin_password)
    create_response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Delete Resident',
            'phone': f"+7999{str(uuid4().int)[-7:]}",
            'plot_number': str(300000 + (uuid4().int % 600000)),
        },
    )
    assert create_response.status_code == 200
    user_id = int(create_response.json()['id'])
    dependency_ids = asyncio.run(_attach_user_deletion_dependencies(user_id))

    removed_gate_keys: list[int] = []
    monkeypatch.setattr(
        'backend.app.services.user_accounts.gate_client.remove_key',
        lambda gate_key_id: removed_gate_keys.append(gate_key_id) or True,
    )

    delete_response = client.delete(
        f'/api/admin/users/{user_id}',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert delete_response.status_code == 200
    assert sorted(removed_gate_keys) == [88003, 88004, 88005]

    state = asyncio.run(_load_user_deletion_state(user_id, dependency_ids))
    assert state == {
        "user_exists": False,
        "request_exists": False,
        "access_key_exists": False,
        "access_permission_exists": False,
        "access_event_exists": False,
        "log_user_id": None,
    }


def test_admin_create_user_links_existing_gate_access_by_phone(client, monkeypatch):
    admin_login = f'admin_link_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Link', plot_number='950', is_admin=True))

    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    plot_number = str(700 + (uuid4().int % 200))

    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.get_key_permissions',
        lambda external_key_id: [{"access_point_id": 21, "access_point_name": "North"}],
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.add_permanent_key',
        lambda **kwargs: 88002,
    )

    admin_token = _api_login(client, admin_login, admin_password)
    create_response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Admin Linked',
            'phone': phone_number,
            'plot_number': plot_number,
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()

    async def _load_linked_request() -> tuple[Request, User]:
        async with SessionLocal() as session:
            user = await session.get(User, int(created['id']))
            assert user is not None
            request_query = await session.execute(
                select(Request).where(
                    Request.resident_id == user.id,
                    Request.key_type == "Phone",
                    Request.status == "active",
                )
            )
            request = request_query.scalar_one()
            return request, user

    linked_request, linked_user = asyncio.run(_load_linked_request())
    assert linked_user.gate_user_id == 88002
    assert linked_request.gate_key_id == 88002
    assert linked_request.key_value == phone_number
    assert linked_request.access_point_ids == [21]


def test_admin_monitor_endpoint_returns_app_open_events(client, monkeypatch):
    admin_login = f'admin_monitor_{uuid4().hex[:6]}'
    resident_login = f'resident_monitor_{uuid4().hex[:6]}'
    password = 'demo123'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Monitor', plot_number='901', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Monitor', plot_number='404'))

    resident_token = _api_login(client, resident_login, password)
    create_response = client.post(
        '/api/requests/',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={
            'key_type': 'VehicleNumber',
            'key_value': f'A{uuid4().hex[:5]}',
            'access_point_ids': [1],
            'is_permanent': True,
        },
    )
    assert create_response.status_code == 200

    open_response = client.post(
        '/api/access/open',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={'access_point_id': 1},
    )
    assert open_response.status_code == 200

    def fake_gate_events(limit: int):
        now = datetime.now(timezone.utc)
        return [
            {
                'index': 10000 + item,
                'time': (now + timedelta(seconds=item)).isoformat(),
                'event_code': 1,
                'access_point_id': 19,
                'unit': f'Gate {item}',
                'message': 'Gate event',
                'name': '',
                'user_ptr': None,
            }
            for item in range(limit)
        ]

    monkeypatch.setattr('backend.app.services.admin_monitor.gate_client.get_recent_events', fake_gate_events)

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/monitor', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    assert body['total'] > 120
    app_event = next(item for item in body['items'] if item['source'] == 'app')
    assert app_event['actor_login'] == resident_login
    assert app_event['access_point_id'] == 1
    assert app_event['app_request_id'] == create_response.json()['id']
    assert app_event['gate_key_id'] is not None


def test_admin_monitor_enriches_gate_events_with_app_actor(client, monkeypatch):
    admin_login = f'admin_monitor_link_{uuid4().hex[:6]}'
    resident_login = f'resident_monitor_link_{uuid4().hex[:6]}'
    password = 'demo123'
    gate_event_index = 555001
    key_value = f'A{uuid4().hex[:5]}'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Monitor', plot_number='901', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Linked', plot_number='405'))

    monkeypatch.setattr(
        'backend.app.services.access.gate_client.open_access_point',
        lambda access_point_id, key_external_id=None: GateOpenResult(
            success=True,
            message='Opened by Gate Terminal',
            details={
                'transport': 'gateterm_ui',
                'observed_event': {
                    'index': gate_event_index,
                    'event_code': 1,
                    'name': 'Админ',
                    'unit': 'Gate Entry',
                },
            },
        ),
    )
    monkeypatch.setattr(
        'backend.app.services.admin_monitor.gate_client.get_recent_events',
        lambda limit: [
            {
                'index': gate_event_index,
                'time': datetime.now(timezone.utc).isoformat(),
                'event_code': 1,
                'access_point_id': 1,
                'unit': 'Gate Entry',
                'message': 'Opened by operator',
                'name': 'Админ',
                'user_ptr': 9001,
            }
        ],
    )

    resident_token = _api_login(client, resident_login, password)
    create_response = client.post(
        '/api/requests/',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={
            'key_type': 'VehicleNumber',
            'key_value': key_value,
            'access_point_ids': [1],
            'is_permanent': True,
        },
    )
    assert create_response.status_code == 200

    open_response = client.post(
        '/api/access/open',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={'access_point_id': 1},
    )
    assert open_response.status_code == 200

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/monitor?limit=10', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    gate_event = next(item for item in body['items'] if item['id'] == f'gate-{gate_event_index}')
    assert gate_event['source'] == 'gate'
    assert gate_event['actor_login'] == resident_login
    assert gate_event['actor_name'] == 'Resident Linked'
    assert gate_event['key_type'] == 'VehicleNumber'
    assert gate_event['key_value'] == key_value.upper()
    assert gate_event['app_request_id'] == create_response.json()['id']
    assert gate_event['gate_name'] == 'Админ'
    assert gate_event['gate_original_name'] == 'Админ'
    assert gate_event['message'] == 'Открыто из приложения'
    assert not any(item['source'] == 'app' and item['gate_event_index'] == gate_event_index for item in body['items'])


def test_admin_monitor_enriches_gate_events_by_key_when_observed_index_is_missing(client, monkeypatch):
    admin_login = f'admin_monitor_key_{uuid4().hex[:6]}'
    resident_login = f'resident_monitor_key_{uuid4().hex[:6]}'
    password = 'demo123'
    gate_key_id = 771001
    gate_event_index = 555002
    wicket_point_id = get_settings().gate_action_map["wicket_north"]
    key_value = f'B{uuid4().hex[:5]}'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Monitor', plot_number='901', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Wicket', plot_number='406'))

    monkeypatch.setattr(
        'backend.app.services.requests.gate_client.add_permanent_key',
        lambda **kwargs: gate_key_id,
    )
    monkeypatch.setattr(
        'backend.app.services.access.gate_client.open_access_point',
        lambda access_point_id, key_external_id=None: GateOpenResult(
            success=True,
            message='Opened by Gate Terminal',
            details={'transport': 'gateterm_ui'},
        ),
    )
    monkeypatch.setattr(
        'backend.app.services.admin_monitor.gate_client.get_recent_events',
        lambda limit: [
            {
                'index': gate_event_index,
                'time': datetime.now(timezone.utc).isoformat(),
                'event_code': 2,
                'access_point_id': wicket_point_id,
                'unit': 'North Wicket',
                'message': 'Opened by key',
                'name': '',
                'user_ptr': gate_key_id,
            }
        ],
    )

    resident_token = _api_login(client, resident_login, password)
    create_response = client.post(
        '/api/requests/',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={
            'key_type': 'VehicleNumber',
            'key_value': key_value,
            'access_point_ids': [wicket_point_id],
            'is_permanent': True,
        },
    )
    assert create_response.status_code == 200

    open_response = client.post(
        '/api/access/open',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={'access_point_id': wicket_point_id},
    )
    assert open_response.status_code == 200

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/monitor?limit=10', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    gate_event = next(item for item in body['items'] if item['id'] == f'gate-{gate_event_index}')
    assert gate_event['source'] == 'gate'
    assert gate_event['actor_login'] == resident_login
    assert gate_event['actor_name'] == 'Resident Wicket'
    assert gate_event['key_type'] == 'VehicleNumber'
    assert gate_event['key_value'] == key_value.upper()
    assert gate_event['app_request_id'] == create_response.json()['id']
    assert gate_event['gate_user_ptr'] == gate_key_id
    assert gate_event['message'] == 'Открыто из приложения'
    assert not any(item['source'] == 'app' and item['app_request_id'] == create_response.json()['id'] for item in body['items'])


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
