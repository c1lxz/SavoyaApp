from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.models import Request, User
from backend.app.services.auth import hash_password
from backend.app.services.gate import GateOpenResult, gate_client


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


def test_access_events_are_logged(client):
    headers, _ = _create_user_and_login(client)
    _create_permanent_request(client, headers, [1])

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 1})
    request_id = opened.json()["request_id"]

    events = client.get("/api/access/events/my", headers=headers)
    assert events.status_code == 200
    rows = events.json()
    assert any(item["request_id"] == request_id for item in rows)


def test_access_open_exit_completes_courier_request_and_removes_gate_key(client):
    headers, user_id = _create_user_and_login(client)
    request_id = asyncio.run(_insert_active_courier_request(user_id, 2, 200501))

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    try:
        opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 2})
        assert opened.status_code == 200
        assert opened.json()["status"] == "success"
    finally:
        gate_client.remove_key = original_remove_key

    assert removed_key_ids == [200501]

    async def _assert_request_completed() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            assert row.status == "completed"
            assert row.cancelled_at is not None

    asyncio.run(_assert_request_completed())
