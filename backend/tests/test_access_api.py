from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models import AccessEventLog, AccessKey, AccessPermission, Request, User
from backend.app.services.access import process_courier_gate_entry_events
from backend.app.services.auth import hash_password
from backend.app.services.gate import GateOpenResult, gate_client
from backend.app.services.requests import cleanup_expired_requests


async def _ensure_user(login: str, password: str) -> None:
    async with SessionLocal() as session:
        query = await session.execute(select(User).where(User.login == login))
        user = query.scalar_one_or_none()
        if user is None:
            session.add(
                User(
                    phone=f"+7999{str(uuid4().int)[:7]}",
                    login=login,
                    password_hash=hash_password(password),
                    name=f"User {login}",
                    apartment="1",
                    plot_number="1",
                    is_admin=False,
                    is_active=True,
                )
            )
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
        await session.commit()


async def _insert_active_request_without_key(user_id: int, access_point_id: int) -> None:
    async with SessionLocal() as session:
        session.add(
            Request(
                resident_id=user_id,
                key_type="VehicleNumber",
                key_value=f"NOKEY{access_point_id}_{uuid4().hex[:6]}",
                gate_key_id=None,
                access_point_ids=[access_point_id],
                is_permanent=True,
                expires_at=None,
                status="active",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


async def _insert_active_courier_request(user_id: int, access_point_id: int, gate_key_id: int) -> int:
    async with SessionLocal() as session:
        row = Request(
            resident_id=user_id,
            key_type="VehicleNumber",
            key_value=f"COURIER{uuid4().hex[:5]}",
            gate_key_id=gate_key_id,
            access_point_ids=[access_point_id],
            is_permanent=False,
            is_courier=True,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0),
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        request_id = int(row.id)
        await session.commit()
        return request_id


async def _age_latest_open_event(user_id: int, access_point_id: int, seconds: int) -> None:
    async with SessionLocal() as session:
        query = await session.execute(
            select(AccessEventLog)
            .where(
                AccessEventLog.user_id == user_id,
                AccessEventLog.access_point_id == access_point_id,
                AccessEventLog.action == "open",
            )
            .order_by(AccessEventLog.created_at.desc())
            .limit(1)
        )
        row = query.scalar_one()
        row.created_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        await session.commit()


def _create_user_and_login(client) -> tuple[dict[str, str], int]:
    login = f"user_{uuid4().hex[:8]}"
    password = "demo123"
    asyncio.run(_ensure_user(login, password))
    auth = client.post("/api/auth/login", json={"login": login, "password": password})
    assert auth.status_code == 200
    data = auth.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, int(data["user"]["id"])


def _create_permanent_request(client, headers: dict[str, str], access_point_ids: list[int]) -> None:
    response = client.post(
        "/api/requests/",
        headers=headers,
        json={
            "key_type": "VehicleNumber",
            "key_value": f"A{uuid4().hex[:5]}",
            "access_point_ids": access_point_ids,
            "is_permanent": True,
        },
    )
    assert response.status_code == 200


def test_access_open_success_for_allowed_point(client):
    headers, _ = _create_user_and_login(client)
    _create_permanent_request(client, headers, [1])

    points = client.get("/api/access/points/my", headers=headers)
    assert points.status_code == 200
    assert any(item["id"] == 1 for item in points.json())

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
    assert opened.status_code == 200
    body = opened.json()
    assert body["status"] == "success"
    assert body["request_id"]


def test_access_open_forbidden_without_permission(client):
    headers, _ = _create_user_and_login(client)
    _create_permanent_request(client, headers, [1])

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 2})
    assert opened.status_code == 403
    assert opened.json()["detail"]["code"] == "forbidden"


def test_access_open_fails_without_key(client):
    headers, user_id = _create_user_and_login(client)
    asyncio.run(_insert_active_request_without_key(user_id, 3))

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 3})
    assert opened.status_code == 404
    assert opened.json()["detail"]["code"] == "key_not_found"


def test_access_open_fails_for_missing_access_point(client):
    headers, _ = _create_user_and_login(client)
    _create_permanent_request(client, headers, [1])

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 99999})
    assert opened.status_code == 404
    assert opened.json()["detail"]["code"] == "access_point_not_found"


def test_access_open_duplicate_request(client):
    headers, _ = _create_user_and_login(client)
    _create_permanent_request(client, headers, [1])

    first = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
    assert first.status_code == 200

    second = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate_request"


def test_access_open_cooldown_is_per_user_and_access_point(client):
    headers, user_id = _create_user_and_login(client)
    _create_permanent_request(client, headers, [1, 2, 3])

    first_entry = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
    assert first_entry.status_code == 200
    asyncio.run(_age_latest_open_event(user_id, 1, seconds=6))

    repeated_entry = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
    assert repeated_entry.status_code == 429
    repeated_entry_detail = repeated_entry.json()["detail"]
    assert repeated_entry_detail["code"] == "open_cooldown"
    assert "Подождите" in repeated_entry_detail["message"]
    assert repeated_entry_detail["retry_after_seconds"] <= 10

    other_barrier = client.post("/api/access/open", headers=headers, json={"access_point_id": 2})
    assert other_barrier.status_code == 200

    first_wicket = client.post("/api/access/open", headers=headers, json={"access_point_id": 3})
    assert first_wicket.status_code == 200
    asyncio.run(_age_latest_open_event(user_id, 3, seconds=6))

    repeated_wicket = client.post("/api/access/open", headers=headers, json={"access_point_id": 3})
    assert repeated_wicket.status_code == 429
    repeated_wicket_detail = repeated_wicket.json()["detail"]
    assert repeated_wicket_detail["code"] == "open_cooldown"
    assert repeated_wicket_detail["retry_after_seconds"] <= 10


def test_compat_gate_open_returns_cooldown_message(client):
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    _create_permanent_request(client, headers, [entry_point_id])

    first = client.post("/gates/open-action", headers=headers, json={"action": "entry"})
    assert first.status_code == 200
    assert first.json()["success"] is True
    asyncio.run(_age_latest_open_event(user_id, entry_point_id, seconds=6))

    repeated = client.post("/gates/open-action", headers=headers, json={"action": "entry"})
    assert repeated.status_code == 200
    body = repeated.json()
    assert body["success"] is False
    assert body["errorCode"] == "open_cooldown"
    assert body["retryAfterSeconds"] <= 10
    assert "Подождите" in body["message"]


def test_access_open_integration_error(client):
    headers, _ = _create_user_and_login(client)
    _create_permanent_request(client, headers, [2])

    original = gate_client.open_access_point
    gate_client.open_access_point = lambda access_point_id, key_external_id=None: GateOpenResult(
        success=False,
        message="Bridge offline",
        code="integration_unavailable",
    )
    try:
        opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 2})
        assert opened.status_code == 200
        body = opened.json()
        assert body["status"] == "failed"
        assert body["message"] == "Bridge offline"
    finally:
        gate_client.open_access_point = original


def test_access_open_bridge_exception_records_failed_event_and_allows_retry(client):
    headers, _ = _create_user_and_login(client)
    _create_permanent_request(client, headers, [2])

    original = gate_client.open_access_point

    def _raise_bridge_error(access_point_id, key_external_id=None):
        raise RuntimeError("GateTerm UI open failed")

    gate_client.open_access_point = _raise_bridge_error
    try:
        failed = client.post("/api/access/open", headers=headers, json={"access_point_id": 2})
        assert failed.status_code == 200
        failed_body = failed.json()
        assert failed_body["status"] == "failed"
        assert "Gate bridge error" in failed_body["message"]
        failed_request_id = failed_body["request_id"]
    finally:
        gate_client.open_access_point = original

    retry = client.post("/api/access/open", headers=headers, json={"access_point_id": 2})
    assert retry.status_code == 200
    assert retry.json()["status"] == "success"

    events = client.get("/api/access/events/my", headers=headers)
    failed_event = next(item for item in events.json() if item["request_id"] == failed_request_id)
    assert failed_event["status"] == "failed"
    assert failed_event["error_code"] == "gate_bridge_error"


def test_access_events_are_logged(client):
    headers, _ = _create_user_and_login(client)
    _create_permanent_request(client, headers, [1])

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
    request_id = opened.json()["request_id"]

    events = client.get("/api/access/events/my", headers=headers)
    assert events.status_code == 200
    rows = events.json()
    assert any(item["request_id"] == request_id for item in rows)


def test_access_events_include_gate_diagnostics(client):
    headers, _ = _create_user_and_login(client)
    _create_permanent_request(client, headers, [1])

    original = gate_client.open_access_point
    gate_client.open_access_point = lambda access_point_id, key_external_id=None: GateOpenResult(
        success=True,
        message="Prepared in dry-run",
        details={"transport": "dry_run", "packet": {"frame_hex": "2026073"}},
    )
    try:
        opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
        assert opened.status_code == 200
        request_id = opened.json()["request_id"]

        events = client.get("/api/access/events/my", headers=headers)
        assert events.status_code == 200
        row = next(item for item in events.json() if item["request_id"] == request_id)
        assert row["details"]["gate_result"]["transport"] == "dry_run"
        assert row["details"]["gate_result"]["packet"]["frame_hex"] == "2026073"
    finally:
        gate_client.open_access_point = original


def test_access_open_entry_schedules_courier_request_expiration(client):
    headers, user_id = _create_user_and_login(client)
    request_id = asyncio.run(_insert_active_courier_request(user_id, 1, 200501))

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    try:
        opened_at = datetime.now(timezone.utc)
        opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
        assert opened.status_code == 200
        assert opened.json()["status"] == "success"
    finally:
        gate_client.remove_key = original_remove_key

    assert removed_key_ids == []

    async def _assert_request_scheduled() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            assert row.status == "active"
            assert row.cancelled_at is None
            assert row.expires_at is not None
            expires_at = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
            remaining = expires_at - opened_at
            assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1)
            key_query = await session.execute(
                select(AccessKey).where(AccessKey.user_id == user_id, AccessKey.external_id == "200501")
            )
            key = key_query.scalar_one()
            assert key.is_active is True
            assert key.valid_to == row.expires_at
            permissions_query = await session.execute(select(AccessPermission).where(AccessPermission.key_id == key.id))
            permissions = list(permissions_query.scalars().all())
            assert permissions
            assert all(permission.is_allowed is True for permission in permissions)
            assert all(permission.valid_to == row.expires_at for permission in permissions)

    asyncio.run(_assert_request_scheduled())


def test_cleanup_expired_courier_request_removes_gate_key_after_entry_ttl(client):
    headers, user_id = _create_user_and_login(client)
    request_id = asyncio.run(_insert_active_courier_request(user_id, 1, 200551))

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
    assert opened.status_code == 200

    async def _expire_and_cleanup() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(_expire_and_cleanup())

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    try:
        async def _cleanup() -> int:
            async with SessionLocal() as session:
                return await cleanup_expired_requests(session)

        changed = asyncio.run(_cleanup())
    finally:
        gate_client.remove_key = original_remove_key

    assert changed == 1
    assert removed_key_ids == [200551]

    async def _assert_request_expired() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            assert row.status == "expired"
            key_query = await session.execute(
                select(AccessKey).where(AccessKey.user_id == user_id, AccessKey.external_id == "200551")
            )
            key = key_query.scalar_one()
            assert key.is_active is False
            permissions_query = await session.execute(select(AccessPermission).where(AccessPermission.key_id == key.id))
            assert all(permission.is_allowed is False for permission in permissions_query.scalars().all())

    asyncio.run(_assert_request_expired())


def test_access_open_exit_does_not_complete_courier_request(client):
    headers, user_id = _create_user_and_login(client)
    request_id = asyncio.run(_insert_active_courier_request(user_id, 2, 200601))

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    try:
        opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 2})
        assert opened.status_code == 200
        assert opened.json()["status"] == "success"
    finally:
        gate_client.remove_key = original_remove_key

    assert removed_key_ids == []

    async def _assert_request_still_active() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            assert row.status == "active"
            assert row.cancelled_at is None

    asyncio.run(_assert_request_still_active())


def test_access_open_entry_schedules_vehicle_and_phone_courier_companions(client):
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    phone_number = f"7911{str(uuid4().int)[:7]}"
    create_response = client.post(
        "/passes",
        headers=headers,
        json={
            "carNumber": f"К{uuid4().hex[:5]}",
            "plotNumber": "77",
            "phoneNumber": phone_number,
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "isPermanent": False,
            "isCourier": True,
        },
    )
    assert create_response.status_code == 200

    async def _active_courier_request_ids() -> list[int]:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            rows = list(query.scalars().all())
            assert {row.key_type for row in rows} == {"VehicleNumber", "Phone"}
            return [int(row.id) for row in rows]

    request_ids = asyncio.run(_active_courier_request_ids())
    opened_at = datetime.now(timezone.utc)
    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    assert opened.status_code == 200
    body = opened.json()
    assert body["status"] == "success"

    async def _assert_all_courier_requests_scheduled() -> None:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            rows = list(query.scalars().all())
            assert len(rows) == 2
            assert sorted(row.id for row in rows) == sorted(request_ids)
            assert all(row.status == "active" for row in rows)
            assert all(row.cancelled_at is None for row in rows)
            expires_values = {row.expires_at for row in rows}
            assert len(expires_values) == 1
            expires_at = next(iter(expires_values))
            assert expires_at is not None
            normalized = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
            remaining = normalized - opened_at
            assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1)

    asyncio.run(_assert_all_courier_requests_scheduled())


def test_gate_entry_event_schedules_phone_opened_courier_pass(client):
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    phone_number = f"7922{str(uuid4().int)[:7]}"
    create_response = client.post(
        "/passes",
        headers=headers,
        json={
            "carNumber": f"TST{uuid4().hex[:5]}",
            "plotNumber": "78",
            "phoneNumber": phone_number,
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "isPermanent": False,
            "isCourier": True,
        },
    )
    assert create_response.status_code == 200

    async def _active_courier_rows() -> list[Request]:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            return list(query.scalars().all())

    active_rows = asyncio.run(_active_courier_rows())
    assert {row.key_type for row in active_rows} == {"VehicleNumber", "Phone"}
    phone_row = next(row for row in active_rows if row.key_type == "Phone")

    async def _remove_entry_reader_from_vehicle_part() -> None:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request).where(
                    Request.resident_id == user_id,
                    Request.status == "active",
                    Request.is_courier.is_(True),
                    Request.key_type == "VehicleNumber",
                )
            )
            vehicle_row = query.scalar_one()
            vehicle_row.access_point_ids = [point_id for point_id in vehicle_row.access_point_ids if point_id != entry_point_id]
            await session.commit()

    asyncio.run(_remove_entry_reader_from_vehicle_part())

    async def _process_gate_event() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 900001,
                        "event_type": 1,
                        "event_code": 2,
                        "access_point_id": entry_point_id,
                        "unit": "Считыватель въезд GSM",
                        "message": "Проход по ключу разрешен",
                        "name": phone_number,
                        "user_ptr": phone_row.gate_key_id,
                    },
                    {
                        "index": 900002,
                        "event_type": 1,
                        "event_code": 8,
                        "access_point_id": entry_point_id,
                        "unit": "Считыватель въезд GSM",
                        "message": "Проход совершен",
                        "name": phone_number,
                        "user_ptr": phone_row.gate_key_id,
                    },
                ],
            )

    event_at = datetime.now(timezone.utc)
    scheduled_count = asyncio.run(_process_gate_event())
    assert scheduled_count == 2

    async def _assert_courier_event_schedule() -> None:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            rows = list(query.scalars().all())
            assert len(rows) == 2
            assert all(row.status == "active" for row in rows)
            expires_values = {row.expires_at for row in rows}
            assert len(expires_values) == 1
            expires_at = next(iter(expires_values))
            assert expires_at is not None
            normalized = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
            remaining = normalized - event_at
            assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1)

            log_query = await session.execute(
                select(AccessEventLog).where(AccessEventLog.request_id == "gate-entry-900001")
            )
            log = log_query.scalar_one()
            assert log.action == "courier_gate_entry"
            assert sorted(log.details["courier_scheduled_request_ids"]) == sorted([row.id for row in rows])
            assert log.details["courier_cleanup"] == "scheduled_after_entry"

    asyncio.run(_assert_courier_event_schedule())


def test_gate_entry_event_schedules_vehicle_camera_opened_courier_pass(client):
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    phone_number = f"7933{str(uuid4().int)[:7]}"
    create_response = client.post(
        "/passes",
        headers=headers,
        json={
            "carNumber": f"CAM{uuid4().hex[:5]}",
            "plotNumber": "79",
            "phoneNumber": phone_number,
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "isPermanent": False,
            "isCourier": True,
        },
    )
    assert create_response.status_code == 200

    async def _active_courier_rows() -> list[Request]:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            return list(query.scalars().all())

    active_rows = asyncio.run(_active_courier_rows())
    assert {row.key_type for row in active_rows} == {"VehicleNumber", "Phone"}
    vehicle_row = next(row for row in active_rows if row.key_type == "VehicleNumber")

    async def _process_camera_event() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 900101,
                        "event_type": 1,
                        "event_code": 2,
                        "access_point_id": entry_point_id,
                        "unit": "Камера Въезда",
                        "message": "Проход по ключу разрешен",
                        "name": vehicle_row.key_value,
                        "user_ptr": vehicle_row.gate_key_id,
                    }
                ],
            )

    scheduled_count = asyncio.run(_process_camera_event())
    assert scheduled_count == 2

    async def _assert_camera_event_schedule() -> None:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            rows = list(query.scalars().all())
            assert len(rows) == 2
            assert all(row.status == "active" for row in rows)
            assert all(row.expires_at is not None for row in rows)

            log_query = await session.execute(
                select(AccessEventLog).where(AccessEventLog.request_id == "gate-entry-900101")
            )
            log = log_query.scalar_one()
            assert log.action == "courier_gate_entry"
            assert sorted(log.details["courier_scheduled_request_ids"]) == sorted([row.id for row in rows])

    asyncio.run(_assert_camera_event_schedule())


def test_gate_entry_event_schedules_gsm_phone_opened_courier_pass(client):
    headers, user_id = _create_user_and_login(client)
    gsm_entry_point_id = get_settings().gate_action_map["wicket_admin"]
    phone_number = f"7944{str(uuid4().int)[:7]}"
    create_response = client.post(
        "/passes",
        headers=headers,
        json={
            "carNumber": f"GSM{uuid4().hex[:5]}",
            "plotNumber": "80",
            "phoneNumber": phone_number,
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "isPermanent": False,
            "isCourier": True,
        },
    )
    assert create_response.status_code == 200

    async def _phone_row() -> Request:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request).where(
                    Request.resident_id == user_id,
                    Request.status == "active",
                    Request.is_courier.is_(True),
                    Request.key_type == "Phone",
                )
            )
            return query.scalar_one()

    phone_row = asyncio.run(_phone_row())
    assert gsm_entry_point_id in phone_row.access_point_ids

    async def _process_gsm_event() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 900201,
                        "event_type": 1,
                        "event_code": 2,
                        "access_point_id": gsm_entry_point_id,
                        "unit": "Считыватель въезд GSM",
                        "message": "Проход по ключу разрешен",
                        "name": phone_number,
                        "user_ptr": phone_row.gate_key_id,
                    }
                ],
            )

    scheduled_count = asyncio.run(_process_gsm_event())
    assert scheduled_count == 2

    async def _assert_gsm_event_schedule() -> None:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            rows = list(query.scalars().all())
            assert len(rows) == 2
            assert all(row.status == "active" for row in rows)
            assert all(row.expires_at is not None for row in rows)

            log_query = await session.execute(
                select(AccessEventLog).where(AccessEventLog.request_id == "gate-entry-900201")
            )
            log = log_query.scalar_one()
            assert log.action == "courier_gate_entry"
            assert log.details["courier_cleanup"] == "scheduled_after_entry"

    asyncio.run(_assert_gsm_event_schedule())
