from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.models import Request, User
from backend.app.services.auth import hash_password
from backend.app.services.gate import gate_client


async def _ensure_user(login: str, password: str, is_active: bool = True) -> int:
    async with SessionLocal() as session:
        query = await session.execute(select(User).where(User.login == login))
        user = query.scalar_one_or_none()
        if user is None:
            user = User(
                phone=f"+7999{str(uuid4().int)[:7]}",
                login=login,
                password_hash=hash_password(password),
                name=f"User {login}",
                apartment="1",
                plot_number="1",
                is_admin=False,
                is_active=is_active,
            )
            session.add(user)
            await session.flush()
            user_id = int(user.id)
        else:
            user.password_hash = hash_password(password)
            user.is_active = is_active
            user_id = int(user.id)
        await session.commit()
        return user_id


def _create_user_and_login(client) -> tuple[dict[str, str], int]:
    login = f"user_{uuid4().hex[:8]}"
    password = "demo123"
    user_id = asyncio.run(_ensure_user(login, password, is_active=True))
    auth = client.post("/api/auth/login", json={"login": login, "password": password})
    assert auth.status_code == 200
    data = auth.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, user_id


async def _insert_permanent_request(user_id: int, key_value: str, gate_key_id: int) -> int:
    async with SessionLocal() as session:
        row = Request(
            resident_id=user_id,
            key_type="VehicleNumber",
            key_value=key_value,
            gate_key_id=gate_key_id,
            access_point_ids=[1],
            is_permanent=True,
            expires_at=None,
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        request_id = int(row.id)
        await session.commit()
        return request_id


def test_create_request_with_empty_access_points_returns_422(client):
    headers, _ = _create_user_and_login(client)
    response = client.post(
        "/api/requests/",
        headers=headers,
        json={
            "key_type": "VehicleNumber",
            "key_value": f"A{uuid4().hex[:6]}",
            "access_point_ids": [],
            "is_permanent": True,
        },
    )
    assert response.status_code == 422


def test_login_inactive_user_returns_403(client):
    login = f"inactive_{uuid4().hex[:8]}"
    password = "demo123"
    asyncio.run(_ensure_user(login, password, is_active=False))

    response = client.post("/api/auth/login", json={"login": login, "password": password})
    assert response.status_code == 403
    assert response.json()["detail"] == "Пользователь деактивирован"


def test_cancel_permanent_request_deactivates_gate_key(client):
    headers, user_id = _create_user_and_login(client)
    request_id = asyncio.run(_insert_permanent_request(user_id, key_value=f"K{uuid4().hex[:6]}", gate_key_id=100501))

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id))
    try:
        response = client.delete(f"/api/requests/{request_id}", headers=headers)
        assert response.status_code == 200
    finally:
        gate_client.remove_key = original_remove_key

    assert removed_key_ids == [100501]
