from __future__ import annotations

import asyncio
import sqlite3
import time
from uuid import uuid4

from backend.app.database import SessionLocal, engine
from backend.app.models import Request, User
from backend.app.services import requests as request_service


async def create_pass() -> tuple[int, int]:
    async with SessionLocal() as session:
        user = User(phone=f"+7{str(uuid4().int)[:10]}", name="Before deletion", is_active=True)
        session.add(user)
        await session.flush()
        request = Request(
            resident_id=user.id, key_type="VehicleNumber", key_value="TEST123",
            gate_key_id=55501, access_point_ids=[], is_permanent=True, status="active",
        )
        session.add(request)
        await session.commit()
        return request.id, user.id


def test_gate_revocation_does_not_hold_sqlite_writer_lock(client, monkeypatch):
    async def scenario():
        request_id, user_id = await create_pass()

        def revoke(key_id):
            assert key_id == 55501
            with sqlite3.connect(engine.url.database, timeout=0.2) as other_writer:
                assert other_writer.execute("SELECT id FROM requests WHERE id=?", (request_id,)).fetchone()
                other_writer.execute("UPDATE users SET name=? WHERE id=?", ("Concurrent update", user_id))
            return True

        monkeypatch.setattr(request_service.gate_client, "remove_key", revoke)
        monkeypatch.setattr(request_service, "_request_deletion_lock", asyncio.Lock())
        async with SessionLocal() as session:
            assert await request_service.delete_request_for_admin(session, request_id) is not None
        async with SessionLocal() as session:
            assert await session.get(Request, request_id) is None
            assert (await session.get(User, user_id)).name == "Concurrent update"

    asyncio.run(scenario())


def test_overlapping_sweep_and_admin_delete_revoke_the_pass_once(client, monkeypatch):
    async def scenario():
        request_id, _ = await create_pass()
        revoked = []

        def revoke(key_id):
            revoked.append(key_id)
            time.sleep(0.1)
            return True

        monkeypatch.setattr(request_service.gate_client, "remove_key", revoke)
        monkeypatch.setattr(request_service, "_request_deletion_lock", asyncio.Lock())
        async with SessionLocal() as first, SessionLocal() as second:
            results = await asyncio.gather(
                request_service.delete_request_for_admin(first, request_id),
                request_service.delete_request_for_admin(second, request_id),
            )
        assert sum(result is not None for result in results) == 1
        assert revoked == [55501]

    asyncio.run(scenario())
