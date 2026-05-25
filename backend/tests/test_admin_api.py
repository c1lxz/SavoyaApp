from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.config import get_settings
from backend.app.messages import BLOCKED_ACCOUNT_MESSAGE
from backend.app.models import AccessEventLog, AccessKey, AccessPermission, AccessPoint, Log, Request, User
from backend.app.schemas import CreateRequestRequest
from backend.app.services.auth import hash_password
from backend.app.services.gate import GateOpenResult
from backend.app.services import requests as request_service


def _is_strong_temporary_password(value: str) -> bool:
    return (
        len(value) == 8
        and sum(1 for char in value if char.isdigit()) == 2
        and sum(1 for char in value if not char.isalnum()) == 1
        and sum(1 for char in value if "\u0410" <= char <= "\u042f") >= 1
        and sum(1 for char in value if "\u0430" <= char <= "\u044f") >= 1
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


async def _create_request_for_user(
    login: str,
    *,
    key_type: str,
    key_value: str,
    access_point_ids: list[int],
    is_permanent: bool = True,
) -> int:
    async with SessionLocal() as session:
        query = await session.execute(select(User).where(User.login == login))
        user = query.scalar_one()
        request = await request_service.create_request(
            session,
            user,
            CreateRequestRequest(
                key_type=key_type,
                key_value=key_value,
                access_point_ids=list(access_point_ids),
                is_permanent=is_permanent,
            ),
        )
        return int(request.id)


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


def test_admin_requests_endpoint_detects_azerbaijan_plate_country(client):
    admin_login = f'admin_plate_{uuid4().hex[:8]}'
    resident_login = f'resident_plate_{uuid4().hex[:8]}'
    password = 'demo123'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Plate', plot_number='911', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Plate', plot_number='404'))

    resident_token = _api_login(client, resident_login, password)
    create_response = client.post(
        '/passes',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={
            'carNumber': '10-PO-749',
            'plotNumber': '404',
            'phoneNumber': None,
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/requests', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    by_login = {item['resident']['login']: item for item in response.json()['items']}
    assert by_login[resident_login]['country_label'] == 'Азербайджан'


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


def test_admin_requests_endpoint_returns_timezone_aware_timestamps(client):
    admin_login = f'admin_tz_{uuid4().hex[:6]}'
    resident_login = f'resident_tz_{uuid4().hex[:6]}'
    password = 'demo123'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Timezone', plot_number='902', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Timezone', plot_number='304'))

    resident_token = _api_login(client, resident_login, password)
    create_response = client.post(
        '/passes',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={
            'carNumber': 'T555TT77',
            'plotNumber': '304',
            'phoneNumber': None,
            'expiresAt': (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(),
            'isPermanent': False,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/requests', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    item = next(row for row in body['items'] if row['resident']['login'] == resident_login)
    created_at = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
    expires_at = datetime.fromisoformat(item['expires_at'].replace('Z', '+00:00'))
    assert created_at.tzinfo is not None
    assert expires_at.tzinfo is not None


def test_admin_request_list_deletes_expired_pass_instead_of_flagging_it(client):
    """An expired temporary pass must be fully deleted (not shown as "Истёк") when the
    admin opens the requests list — same outcome as a manual deletion."""
    admin_login = f'admin_exp_{uuid4().hex[:6]}'
    resident_login = f'resident_exp_{uuid4().hex[:6]}'
    password = 'demo123'
    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Exp', plot_number='903', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Exp', plot_number='417'))

    request_id = asyncio.run(
        _create_request_for_user(
            resident_login,
            key_type='VehicleNumber',
            key_value=f'EXP{uuid4().hex[:5]}',
            access_point_ids=[get_settings().gate_action_map['entry']],
            is_permanent=True,
        )
    )

    async def _make_expired() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            row.is_permanent = False
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(_make_expired())

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/requests', headers={'Authorization': f'Bearer {admin_token}'})
    assert response.status_code == 200
    body = response.json()
    assert all(int(item['id']) != request_id for item in body['items']), (
        "expired pass must be deleted from the admin list, not shown as expired"
    )

    async def _assert_deleted() -> None:
        async with SessionLocal() as session:
            assert await session.get(Request, request_id) is None

    asyncio.run(_assert_deleted())


def test_admin_can_delete_request_without_deleting_user(client):
    admin_login = f'admin_delete_request_{uuid4().hex[:6]}'
    resident_login = f'resident_delete_request_{uuid4().hex[:6]}'
    password = 'demo123'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Delete Request', plot_number='930', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Delete Request', plot_number='415'))

    resident_token = _api_login(client, resident_login, password)
    create_response = client.post(
        '/passes',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={
            'carNumber': 'A555AA77',
            'plotNumber': '415',
            'phoneNumber': '+79990001122',
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )
    assert create_response.status_code == 200
    pass_id = create_response.json()['id']

    admin_token = _api_login(client, admin_login, password)
    delete_response = client.delete(
        f'/api/admin/requests/{pass_id}',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert delete_response.status_code == 200

    resident_passes = client.get(
        '/passes/my',
        headers={'Authorization': f'Bearer {resident_token}'},
    )
    assert resident_passes.status_code == 200
    assert resident_passes.json() == []

    resident_users = client.get(
        f'/api/admin/users?search={resident_login}',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert resident_users.status_code == 200
    listed_users = resident_users.json()['items']
    assert any(item['login'] == resident_login for item in listed_users)


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


def test_admin_delete_user_returns_error_when_gate_cleanup_fails(client, monkeypatch):
    admin_login = f'admin_delete_fail_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Delete Fail', plot_number='951', is_admin=True))

    admin_token = _api_login(client, admin_login, admin_password)
    create_response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Delete Fail Resident',
            'phone': f"+7999{str(uuid4().int)[-7:]}",
            'plot_number': str(310000 + (uuid4().int % 600000)),
        },
    )
    assert create_response.status_code == 200
    user_id = int(create_response.json()['id'])
    dependency_ids = asyncio.run(_attach_user_deletion_dependencies(user_id))

    def _raise_gate_cleanup_error(_gate_key_id: int) -> bool:
        raise RuntimeError('gate busy')

    monkeypatch.setattr(
        'backend.app.services.user_accounts.gate_client.remove_key',
        _raise_gate_cleanup_error,
    )

    delete_response = client.delete(
        f'/api/admin/users/{user_id}',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert delete_response.status_code == 502
    assert delete_response.json() == {
        'detail': {
            'code': 'gate_cleanup_failed',
            'message': 'Не удалось удалить пропуск Gate 88003: gate busy',
        }
    }

    state = asyncio.run(_load_user_deletion_state(user_id, dependency_ids))
    assert state == {
        "user_exists": True,
        "request_exists": True,
        "access_key_exists": True,
        "access_permission_exists": True,
        "access_event_exists": True,
        "log_user_id": user_id,
    }


def test_deleted_user_old_token_cannot_open_gate_or_load_profile(client):
    admin_login = f'admin_delete_session_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Delete Session', plot_number='952', is_admin=True))

    admin_token = _api_login(client, admin_login, admin_password)
    create_response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Session Resident',
            'phone': f"+7999{str(uuid4().int)[-7:]}",
            'plot_number': str(320000 + (uuid4().int % 600000)),
        },
    )
    assert create_response.status_code == 200
    created_user = create_response.json()

    resident_auth = client.post(
        '/api/auth/login',
        json={'login': created_user['login'], 'password': created_user['password']},
    )
    assert resident_auth.status_code == 200
    resident_token = resident_auth.json()['access_token']

    delete_response = client.delete(
        f"/api/admin/users/{created_user['id']}",
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert delete_response.status_code == 200

    me_response = client.get('/user/me', headers={'Authorization': f'Bearer {resident_token}'})
    assert me_response.status_code == 401

    gate_response = client.post(
        '/gates/open-action',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={'action': 'wicket_north'},
    )
    assert gate_response.status_code == 401


def test_admin_create_user_links_existing_gate_access_by_phone(client, monkeypatch):
    admin_login = f'admin_link_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Link', plot_number='950', is_admin=True))

    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    plot_number = str(700 + (uuid4().int % 200))
    expected_access_point_ids = [15, 17, 19, 20, 21, 23, 5, 6]
    captured_gate_calls = []

    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.default_access_point_ids_json',
        '[15,17,19,20,21,23]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gsm_access_point_ids_json',
        '[5,6]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gate_real_integration_enabled',
        True,
    )

    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.get_key_permissions',
        lambda external_key_id: [
            {"access_point_id": 6, "access_point_name": "GSM entry"},
            {"access_point_id": 5, "access_point_name": "GSM exit"},
        ],
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.add_account_phone_key',
        lambda **kwargs: captured_gate_calls.append(dict(kwargs)) or 88002,
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
    assert linked_request.access_point_ids == expected_access_point_ids
    assert captured_gate_calls[0]["access_point_ids"] == expected_access_point_ids


def test_admin_create_user_provisions_gate_phone_access_when_missing(client, monkeypatch):
    admin_login = f'admin_provision_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Provision', plot_number='951', is_admin=True))

    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    plot_number = str(900 + (uuid4().int % 100))
    expected_access_point_ids = [15, 17, 19, 20, 21, 23, 5, 6]
    captured_gate_calls = []

    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.default_access_point_ids_json',
        '[15,17,19,20,21,23]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gsm_access_point_ids_json',
        '[5,6]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gate_real_integration_enabled',
        True,
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.get_key_permissions',
        lambda external_key_id: (_ for _ in ()).throw(RuntimeError('lookup failed')),
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.add_account_phone_key',
        lambda **kwargs: captured_gate_calls.append(dict(kwargs)) or 88004,
    )

    admin_token = _api_login(client, admin_login, admin_password)
    create_response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Admin Provisioned',
            'phone': phone_number,
            'plot_number': plot_number,
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()

    async def _load_provisioned_request() -> tuple[Request, User]:
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

    provisioned_request, provisioned_user = asyncio.run(_load_provisioned_request())
    assert provisioned_user.gate_user_id == 88004
    assert provisioned_request.gate_key_id == 88004
    assert provisioned_request.key_value == phone_number
    assert provisioned_request.contact_phone == phone_number
    assert provisioned_request.access_point_ids == expected_access_point_ids
    assert captured_gate_calls == [
        {
            'key_value': phone_number,
            'phone_number': phone_number,
            'access_point_ids': expected_access_point_ids,
            'resident_name': 'Admin Provisioned',
            'plot_number': plot_number,
        }
    ]


def test_admin_create_user_recovers_gate_phone_key_after_ui_timeout(client, monkeypatch):
    admin_login = f'admin_recover_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Recover', plot_number='951', is_admin=True))

    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    plot_number = str(910 + (uuid4().int % 100))
    expected_access_point_ids = [15, 17, 19, 20, 21, 23, 5, 6]

    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.default_access_point_ids_json',
        '[15,17,19,20,21,23]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gsm_access_point_ids_json',
        '[5,6]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gate_real_integration_enabled',
        True,
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.get_key_permissions',
        lambda external_key_id: [],
    )

    def _raise_timeout(**_kwargs):
        raise RuntimeError('Gate bridge action add_phone_permanent_key_via_ui timed out after 60 seconds')

    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.add_account_phone_key',
        _raise_timeout,
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.resolve_key_id',
        lambda external_key_id: 88008 if external_key_id == phone_number else None,
    )

    admin_token = _api_login(client, admin_login, admin_password)
    create_response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Admin Recovered',
            'phone': phone_number,
            'plot_number': plot_number,
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created['password']

    async def _load_recovered_request() -> tuple[Request, User]:
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

    recovered_request, recovered_user = asyncio.run(_load_recovered_request())
    assert recovered_user.gate_user_id == 88008
    assert recovered_request.gate_key_id == 88008
    assert recovered_request.key_value == phone_number
    assert recovered_request.access_point_ids == expected_access_point_ids


def test_admin_create_user_rolls_back_when_gate_phone_access_is_not_provisioned(client, monkeypatch):
    admin_login = f'admin_gate_fail_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Gate Fail', plot_number='953', is_admin=True))

    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    plot_number = str(700 + (uuid4().int % 100))

    monkeypatch.setattr('backend.app.routers.admin.settings.gate_real_integration_enabled', True)

    async def _fake_link_existing_gate_passes_by_phone(_session, _user):
        return SimpleNamespace(error='gate provisioning failed', linked_count=0)

    monkeypatch.setattr(
        'backend.app.routers.admin.link_existing_gate_passes_by_phone',
        _fake_link_existing_gate_passes_by_phone,
    )

    admin_token = _api_login(client, admin_login, admin_password)
    response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Resident Gate Fail',
            'phone': phone_number,
            'plot_number': plot_number,
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        'detail': {
            'code': 'gate_phone_access_failed',
            'message': 'gate provisioning failed',
        }
    }

    async def _load_user_and_requests() -> tuple[User | None, list[Request]]:
        async with SessionLocal() as session:
            user_query = await session.execute(select(User).where(User.phone == phone_number))
            user = user_query.scalar_one_or_none()
            if user is None:
                return None, []
            request_query = await session.execute(select(Request).where(Request.resident_id == user.id))
            return user, list(request_query.scalars().all())

    user, requests = asyncio.run(_load_user_and_requests())
    assert user is None
    assert requests == []


def test_admin_created_user_can_add_vehicle_pass_without_replacing_phone_pass(client, monkeypatch):
    admin_login = f'admin_vehicle_{uuid4().hex[:6]}'
    admin_password = 'demo123'
    asyncio.run(_ensure_user(admin_login, admin_password, full_name='Admin Vehicle', plot_number='952', is_admin=True))

    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    plot_number = str(800 + (uuid4().int % 100))
    vehicle_number = 'A123AA77'
    captured_gate_calls = []

    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.default_access_point_ids_json',
        '[15,17,19,20,21,23]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gsm_access_point_ids_json',
        '[5,6]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gate_real_integration_enabled',
        True,
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.get_key_permissions',
        lambda external_key_id: [],
    )
    # Vehicle passes are routed to camera-only access points by
    # compatibility._runtime_vehicle_camera_access_point_ids, which queries
    # gate_client.get_access_points.  Provide a deterministic camera set.
    monkeypatch.setattr(
        'backend.app.routers.compatibility.settings.gate_real_integration_enabled',
        True,
    )
    monkeypatch.setattr(
        'backend.app.routers.compatibility.gate_client.get_access_points',
        lambda: [
            {'id': 19, 'name': 'Камера Въезда'},
            {'id': 20, 'name': 'Камера Выезда'},
            {'id': 15, 'name': 'Считыватель Северная калитка'},
        ],
    )

    def _fake_add_permanent_key(**kwargs):
        captured_gate_calls.append(dict(kwargs))
        return 88006 if 'key_type' not in kwargs else 88007

    monkeypatch.setattr(
        'backend.app.services.gate.gate_client.add_account_phone_key',
        _fake_add_permanent_key,
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.add_account_phone_key',
        _fake_add_permanent_key,
    )
    monkeypatch.setattr(
        'backend.app.services.requests.gate_client.add_permanent_key',
        _fake_add_permanent_key,
    )

    admin_token = _api_login(client, admin_login, admin_password)
    create_user_response = client.post(
        '/api/admin/users',
        headers={'Authorization': f'Bearer {admin_token}'},
        json={
            'full_name': 'Resident Vehicle',
            'phone': phone_number,
            'plot_number': plot_number,
        },
    )

    assert create_user_response.status_code == 200
    created_user = create_user_response.json()

    resident_token = _api_login(client, created_user['login'], created_user['password'])
    create_pass_response = client.post(
        '/passes',
        headers={'Authorization': f'Bearer {resident_token}'},
        json={
            'carNumber': vehicle_number,
            'plotNumber': plot_number,
            'phoneNumber': phone_number,
            'expiresAt': None,
            'isPermanent': True,
            'isCourier': False,
        },
    )

    assert create_pass_response.status_code == 200

    async def _load_requests() -> tuple[User, list[Request]]:
        async with SessionLocal() as session:
            user = await session.get(User, int(created_user['id']))
            assert user is not None
            requests_query = await session.execute(
                select(Request)
                .where(
                    Request.resident_id == user.id,
                    Request.status == 'active',
                )
                .order_by(Request.id.asc())
            )
            return user, list(requests_query.scalars().all())

    resident_user, requests = asyncio.run(_load_requests())
    assert resident_user.gate_user_id == 88006
    assert [(item.key_type, item.key_value, item.gate_key_id) for item in requests] == [
        ('Phone', phone_number, 88006),
        ('VehicleNumber', vehicle_number, 88007),
    ]
    assert captured_gate_calls[0] == {
        'key_value': phone_number,
        'phone_number': phone_number,
        'access_point_ids': [15, 17, 19, 20, 21, 23, 5, 6],
        'resident_name': 'Resident Vehicle',
        'plot_number': plot_number,
    }
    assert captured_gate_calls[1] == {
        'key_type': 'VehicleNumber',
        'key_value': vehicle_number,
        'phone_number': phone_number,
        # Vehicle passes are restricted to the entry/exit cameras only.
        'access_point_ids': [19, 20],
        'resident_name': 'Resident Vehicle',
        'plot_number': plot_number,
    }


def test_startup_backfills_missing_gate_phone_requests(monkeypatch):
    from backend.app.services.gate_linking import ensure_users_have_gate_phone_requests

    phone_number = f"+7999{str(uuid4().int)[-7:]}"
    expected_access_point_ids = [15, 17, 19, 20, 21, 23, 5, 6]
    captured_gate_calls = []

    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.default_access_point_ids_json',
        '[15,17,19,20,21,23]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gsm_access_point_ids_json',
        '[5,6]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gate_real_integration_enabled',
        True,
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.get_key_permissions',
        lambda external_key_id: [],
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.add_account_phone_key',
        lambda **kwargs: captured_gate_calls.append(dict(kwargs)) or 88005,
    )

    async def _create_user_without_phone_request() -> int:
        async with SessionLocal() as session:
            user = User(
                phone=phone_number,
                login=f"resident_backfill_{uuid4().hex[:6]}",
                password_hash=hash_password("demo123"),
                name="Resident Backfill",
                apartment="712",
                plot_number="712",
                is_admin=False,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user.id

    user_id = asyncio.run(_create_user_without_phone_request())

    async def _backfill_and_load() -> tuple[int, Request | None, User | None]:
        async with SessionLocal() as session:
            changed = await ensure_users_have_gate_phone_requests(session)
            request_query = await session.execute(
                select(Request).where(
                    Request.resident_id == user_id,
                    Request.key_type == "Phone",
                    Request.status == "active",
                )
            )
            request = request_query.scalar_one_or_none()
            user = await session.get(User, user_id)
            return changed, request, user

    changed, request, user = asyncio.run(_backfill_and_load())
    assert changed >= 1
    assert user is not None
    assert request is not None
    assert user.gate_user_id == 88005
    assert request.gate_key_id == 88005
    assert request.key_value == phone_number
    assert request.contact_phone == phone_number
    assert request.access_point_ids == expected_access_point_ids
    assert any(
        call == {
            'key_value': phone_number,
            'phone_number': phone_number,
            'access_point_ids': expected_access_point_ids,
            'resident_name': 'Resident Backfill',
            'plot_number': '712',
        }
        for call in captured_gate_calls
    )


def test_startup_expands_existing_permanent_phone_access_points(monkeypatch):
    from backend.app.services.gate_linking import ensure_existing_phone_requests_have_configured_access

    expected_access_point_ids = [15, 17, 19, 20, 21, 23, 5, 6]
    captured_gate_calls = []

    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.default_access_point_ids_json',
        '[15,17,19,20,21,23]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.settings.gsm_access_point_ids_json',
        '[5,6]',
    )
    monkeypatch.setattr(
        'backend.app.services.gate_linking.gate_client.add_account_phone_key',
        lambda **kwargs: captured_gate_calls.append(dict(kwargs)) or 88003,
    )

    async def _create_existing_phone_request() -> int:
        async with SessionLocal() as session:
            user = User(
                phone=f"+7999{str(uuid4().int)[-7:]}",
                login=f"linked_existing_{uuid4().hex[:6]}",
                password_hash=hash_password("demo123"),
                name="Linked Existing",
                apartment="711",
                plot_number="711",
                is_admin=False,
                is_active=True,
            )
            session.add(user)
            await session.flush()
            request = Request(
                resident_id=user.id,
                key_type="Phone",
                key_value=user.phone,
                gate_key_id=88001,
                access_point_ids=[6, 5],
                is_permanent=True,
                status="active",
                contact_phone=user.phone,
                plot_number=user.plot_number,
            )
            session.add(request)
            await session.commit()
            return request.id

    request_id = asyncio.run(_create_existing_phone_request())

    async def _expand_and_load() -> Request:
        async with SessionLocal() as session:
            changed = await ensure_existing_phone_requests_have_configured_access(session)
            assert changed == 1
            request = await session.get(Request, request_id)
            assert request is not None
            return request

    expanded_request = asyncio.run(_expand_and_load())
    assert expanded_request.gate_key_id == 88003
    assert expanded_request.access_point_ids == expected_access_point_ids
    assert captured_gate_calls[0]["access_point_ids"] == expected_access_point_ids


def test_admin_monitor_endpoint_returns_app_open_events(client, monkeypatch):
    admin_login = f'admin_monitor_{uuid4().hex[:6]}'
    resident_login = f'resident_monitor_{uuid4().hex[:6]}'
    password = 'demo123'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Monitor', plot_number='901', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Monitor', plot_number='404'))

    resident_token = _api_login(client, resident_login, password)
    created_request_id = asyncio.run(
        _create_request_for_user(
            resident_login,
            key_type='VehicleNumber',
            key_value=f'A{uuid4().hex[:5]}',
            access_point_ids=[1],
        )
    )

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
            for item in range(max(0, limit - 1))
        ]

    monkeypatch.setattr('backend.app.services.admin_monitor.gate_client.get_recent_events', fake_gate_events)

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/monitor', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    assert body['total'] >= 120
    app_event = next(item for item in body['items'] if item['source'] == 'app')
    assert app_event['actor_login'] == resident_login
    assert app_event['access_point_id'] == 1
    assert app_event['app_request_id'] == created_request_id
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
    monkeypatch.setattr(
        'backend.app.services.requests.gate_client.add_permanent_key',
        lambda **kwargs: 9001,
    )

    resident_token = _api_login(client, resident_login, password)
    created_request_id = asyncio.run(
        _create_request_for_user(
            resident_login,
            key_type='VehicleNumber',
            key_value=key_value,
            access_point_ids=[1],
        )
    )

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
    assert gate_event['app_request_id'] == created_request_id
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
    monkeypatch.setattr(
        'backend.app.services.requests.gate_client.add_permanent_key',
        lambda **kwargs: gate_key_id,
    )

    resident_token = _api_login(client, resident_login, password)
    created_request_id = asyncio.run(
        _create_request_for_user(
            resident_login,
            key_type='VehicleNumber',
            key_value=key_value,
            access_point_ids=[wicket_point_id],
        )
    )

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
    assert gate_event['app_request_id'] == created_request_id
    assert gate_event['gate_user_ptr'] == gate_key_id
    assert gate_event['message'] == 'Открыто из приложения'
    assert not any(item['source'] == 'app' and item['app_request_id'] == created_request_id for item in body['items'])


def test_admin_monitor_uses_gate_identity_when_gate_event_has_no_app_match(client, monkeypatch):
    admin_login = f'admin_monitor_gate_{uuid4().hex[:6]}'
    password = 'demo123'
    gate_event_index = 555101

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Monitor', plot_number='901', is_admin=True))

    monkeypatch.setattr(
        'backend.app.services.admin_monitor.gate_client.get_recent_events',
        lambda limit: [
            {
                'index': gate_event_index,
                'time': datetime.now(timezone.utc).isoformat(),
                'event_code': 2,
                'access_point_id': 1,
                'unit': 'Gate Entry',
                'message': 'Opened by key',
                'name': '',
                'user_ptr': 812345,
                'full_name': 'Camera Resident',
                'key_type': 'VehicleNumber',
                'key_value': 'A123AA77',
            }
        ],
    )

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/monitor?limit=10', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    gate_event = next(item for item in body['items'] if item['id'] == f'gate-{gate_event_index}')
    assert gate_event['source'] == 'gate'
    assert gate_event['actor_name'] == 'A123AA77   Camera Resident'
    assert gate_event['key_type'] == 'VehicleNumber'
    assert gate_event['key_value'] == 'A123AA77'
    assert gate_event['gate_name'] == 'A123AA77   Camera Resident'
    assert gate_event['gate_original_name'] is None


def test_admin_monitor_enriches_camera_gate_event_from_backend_request_when_gate_identity_is_blank(client, monkeypatch):
    admin_login = f'admin_monitor_camera_{uuid4().hex[:6]}'
    resident_login = f'resident_camera_{uuid4().hex[:6]}'
    password = 'demo123'
    gate_key_id = 771501
    gate_event_index = 555501
    access_point_id = get_settings().gate_action_map["entry"]
    key_value = 'P345OK77'

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Monitor', plot_number='901', is_admin=True))
    asyncio.run(_ensure_user(resident_login, password, full_name='Resident Camera', plot_number='407'))

    monkeypatch.setattr(
        'backend.app.services.requests.gate_client.add_permanent_key',
        lambda **kwargs: gate_key_id,
    )
    created_request_id = asyncio.run(
        _create_request_for_user(
            resident_login,
            key_type='VehicleNumber',
            key_value=key_value,
            access_point_ids=[access_point_id],
        )
    )
    monkeypatch.setattr(
        'backend.app.services.admin_monitor.gate_client.get_recent_events',
        lambda limit: [
            {
                'index': gate_event_index,
                'time': datetime.now(timezone.utc).isoformat(),
                'event_code': 2,
                'access_point_id': access_point_id,
                'unit': 'Camera Entry',
                'message': 'Camera allowed',
                'name': '',
                'user_ptr': gate_key_id,
                'full_name': None,
                'key_type': None,
                'key_value': None,
            }
        ],
    )

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/monitor?limit=10', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    gate_event = next(item for item in body['items'] if item['id'] == f'gate-{gate_event_index}')
    assert gate_event['source'] == 'gate'
    assert gate_event['actor_login'] == resident_login
    assert gate_event['actor_name'] == 'Resident Camera'
    assert gate_event['key_type'] == 'VehicleNumber'
    assert gate_event['key_value'] == key_value
    assert gate_event['app_request_id'] == created_request_id
    assert gate_event['gate_key_id'] == gate_key_id
    assert gate_event['gate_name'] == f'{key_value}   Resident Camera'
    assert gate_event['gate_original_name'] is None
    assert gate_event['details']['matched_request']['gate_key_id'] == gate_key_id


def test_admin_monitor_uses_inferred_gate_identity_when_raw_gate_name_is_blank(client, monkeypatch):
    admin_login = f'admin_monitor_inferred_{uuid4().hex[:6]}'
    password = 'demo123'
    gate_event_index = 555102

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Monitor', plot_number='901', is_admin=True))

    monkeypatch.setattr(
        'backend.app.services.admin_monitor.gate_client.get_recent_events',
        lambda limit: [
            {
                'index': gate_event_index,
                'time': datetime.now(timezone.utc).isoformat(),
                'event_code': 8,
                'access_point_id': 6,
                'unit': 'GSM Gate',
                'message': 'Opened by call',
                'name': '',
                'user_ptr': 0,
                'full_name': None,
                'key_type': None,
                'key_value': None,
                'inferred_full_name': 'Phone Resident',
                'inferred_key_type': 'Phone',
                'inferred_key_value': '009991234567',
                'identity_source': 'last_used',
            }
        ],
    )

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/monitor?limit=10', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    gate_event = next(item for item in body['items'] if item['id'] == f'gate-{gate_event_index}')
    assert gate_event['source'] == 'gate'
    assert gate_event['actor_name'] == '009991234567   Phone Resident'
    assert gate_event['key_type'] == 'Phone'
    assert gate_event['key_value'] == '009991234567'
    assert gate_event['gate_name'] == '009991234567   Phone Resident'
    assert gate_event['gate_original_name'] is None


def test_admin_monitor_labels_fully_anonymous_gsm_event(client, monkeypatch):
    admin_login = f'admin_monitor_anon_{uuid4().hex[:6]}'
    password = 'demo123'
    gate_event_index = 555103

    asyncio.run(_ensure_user(admin_login, password, full_name='Admin Monitor', plot_number='901', is_admin=True))

    monkeypatch.setattr(
        'backend.app.services.admin_monitor.gate_client.get_recent_events',
        lambda limit: [
            {
                'index': gate_event_index,
                'time': datetime.now(timezone.utc).isoformat(),
                'event_code': 8,
                'access_point_id': 6,
                'unit': 'GSM Gate',
                'message': 'Opened by call',
                'name': '',
                'user_ptr': 0,
                'full_name': None,
                'key_type': None,
                'key_value': None,
            }
        ],
    )

    admin_token = _api_login(client, admin_login, password)
    response = client.get('/api/admin/monitor?limit=10', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    body = response.json()
    gate_event = next(item for item in body['items'] if item['id'] == f'gate-{gate_event_index}')
    assert gate_event['source'] == 'gate'
    assert gate_event['actor_name'] == 'Анонимный GSM'
    assert gate_event['key_type'] is None
    assert gate_event['key_value'] is None
    assert gate_event['gate_name'] == 'Анонимный GSM'
    assert gate_event['gate_original_name'] is None


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
