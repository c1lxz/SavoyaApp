from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models import AccessEventLog, AccessKey, AccessPermission, AccessPoint, Request, User
from backend.app.services import gate_event_worker
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


async def _insert_active_permanent_request(user_id: int, access_point_id: int, gate_key_id: int) -> int:
    """Insert a permanent personal pass directly into the DB (bypasses Gate API)."""
    async with SessionLocal() as session:
        row = Request(
            resident_id=user_id,
            key_type="VehicleNumber",
            key_value=f"PERSONAL{uuid4().hex[:5]}",
            gate_key_id=gate_key_id,
            access_point_ids=[access_point_id],
            is_permanent=True,
            is_courier=False,
            expires_at=None,
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        request_id = int(row.id)
        await session.commit()
        return request_id


async def _ensure_access_point(access_point_id: int, *, name: str, point_type: str = "gate") -> None:
    async with SessionLocal() as session:
        point = await session.get(AccessPoint, access_point_id)
        if point is None:
            session.add(
                AccessPoint(
                    id=access_point_id,
                    name=name,
                    code=f"test-{access_point_id}",
                    type=point_type,
                    is_active=True,
                )
            )
        else:
            point.name = name
            point.code = point.code or f"test-{access_point_id}"
            point.type = point_type
            point.is_active = True
        await session.commit()


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


def test_access_open_success_for_account_without_pass(client):
    headers, _ = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]

    points = client.get("/api/access/points/my", headers=headers)
    assert points.status_code == 200
    assert any(item["id"] == entry_point_id for item in points.json())

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    assert opened.status_code == 200
    body = opened.json()
    assert body["status"] == "success"
    assert body["request_id"]


def test_access_open_forbidden_without_permission(client):
    headers, _ = _create_user_and_login(client)
    asyncio.run(_ensure_access_point(99, name="Restricted Test Gate"))

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 99})
    assert opened.status_code == 403
    assert opened.json()["detail"]["code"] == "forbidden"


def test_access_open_fails_without_key(client):
    headers, user_id = _create_user_and_login(client)
    asyncio.run(_ensure_access_point(98, name="Request Only Gate"))
    asyncio.run(_insert_active_request_without_key(user_id, 98))

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 98})
    assert opened.status_code == 404
    assert opened.json()["detail"]["code"] == "key_not_found"


def test_access_open_fails_for_missing_access_point(client):
    headers, _ = _create_user_and_login(client)

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": 99999})
    assert opened.status_code == 404
    assert opened.json()["detail"]["code"] == "access_point_not_found"


def test_access_open_duplicate_request(client):
    headers, _ = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]

    first = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    assert first.status_code == 200

    second = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate_request"


def test_access_open_cooldown_is_per_user_and_access_point(client):
    headers, user_id = _create_user_and_login(client)
    settings = get_settings()
    entry_point_id = settings.gate_action_map["entry"]
    exit_point_id = settings.gate_action_map["exit"]
    wicket_point_id = settings.gate_action_map["wicket_north"]

    first_entry = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    assert first_entry.status_code == 200
    asyncio.run(_age_latest_open_event(user_id, entry_point_id, seconds=6))

    repeated_entry = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    assert repeated_entry.status_code == 429
    repeated_entry_detail = repeated_entry.json()["detail"]
    assert repeated_entry_detail["code"] == "open_cooldown"
    assert "Подождите" in repeated_entry_detail["message"]
    assert repeated_entry_detail["retry_after_seconds"] <= 10

    other_barrier = client.post("/api/access/open", headers=headers, json={"access_point_id": exit_point_id})
    assert other_barrier.status_code == 200

    first_wicket = client.post("/api/access/open", headers=headers, json={"access_point_id": wicket_point_id})
    assert first_wicket.status_code == 200
    asyncio.run(_age_latest_open_event(user_id, wicket_point_id, seconds=6))

    repeated_wicket = client.post("/api/access/open", headers=headers, json={"access_point_id": wicket_point_id})
    assert repeated_wicket.status_code == 429
    repeated_wicket_detail = repeated_wicket.json()["detail"]
    assert repeated_wicket_detail["code"] == "open_cooldown"
    assert repeated_wicket_detail["retry_after_seconds"] <= 10


def test_compat_gate_open_returns_cooldown_message(client):
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]

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
    entry_point_id = get_settings().gate_action_map["entry"]

    original = gate_client.open_access_point
    gate_client.open_access_point = lambda access_point_id, key_external_id=None: GateOpenResult(
        success=False,
        message="Bridge offline",
        code="integration_unavailable",
    )
    try:
        opened = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
        assert opened.status_code == 200
        body = opened.json()
        assert body["status"] == "failed"
        assert body["message"] == "Bridge offline"
    finally:
        gate_client.open_access_point = original


def test_access_open_bridge_exception_records_failed_event_and_allows_retry(client):
    headers, _ = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]

    original = gate_client.open_access_point

    def _raise_bridge_error(access_point_id, key_external_id=None):
        raise RuntimeError("GateTerm UI open failed")

    gate_client.open_access_point = _raise_bridge_error
    try:
        failed = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
        assert failed.status_code == 200
        failed_body = failed.json()
        assert failed_body["status"] == "failed"
        assert "Gate bridge error" in failed_body["message"]
        failed_request_id = failed_body["request_id"]
    finally:
        gate_client.open_access_point = original

    retry = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    assert retry.status_code == 200
    assert retry.json()["status"] == "success"

    events = client.get("/api/access/events/my", headers=headers)
    failed_event = next(item for item in events.json() if item["request_id"] == failed_request_id)
    assert failed_event["status"] == "failed"
    assert failed_event["error_code"] == "gate_bridge_error"


def test_access_events_are_logged(client):
    headers, _ = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    request_id = opened.json()["request_id"]

    events = client.get("/api/access/events/my", headers=headers)
    assert events.status_code == 200
    rows = events.json()
    assert any(item["request_id"] == request_id for item in rows)


def test_access_events_include_gate_diagnostics(client):
    headers, _ = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]

    original = gate_client.open_access_point
    gate_client.open_access_point = lambda access_point_id, key_external_id=None: GateOpenResult(
        success=True,
        message="Prepared in dry-run",
        details={"transport": "dry_run", "packet": {"frame_hex": "2026073"}},
    )
    try:
        opened = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
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
    entry_point_id = get_settings().gate_action_map["entry"]
    request_id = asyncio.run(_insert_active_courier_request(user_id, entry_point_id, 200501))

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    try:
        opened_at = datetime.now(timezone.utc)
        opened = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
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
    entry_point_id = get_settings().gate_action_map["entry"]
    request_id = asyncio.run(_insert_active_courier_request(user_id, entry_point_id, 200551))

    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
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


def test_sweep_expired_requests_once_deletes_pass_and_removes_gate_key_after_ttl(client):
    """The background sweep must DELETE an expired pass (Gate key + app row), exactly
    like a manual admin deletion — not merely flag it "expired".
    """
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    request_id = asyncio.run(_insert_active_courier_request(user_id, entry_point_id, 200751))

    async def _expire() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(_expire())

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    original_integration = gate_event_worker.settings.gate_real_integration_enabled
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    gate_event_worker.settings.gate_real_integration_enabled = True
    try:
        removed = asyncio.run(gate_event_worker.sweep_expired_requests_once())
    finally:
        gate_client.remove_key = original_remove_key
        gate_event_worker.settings.gate_real_integration_enabled = original_integration

    assert removed == 1
    assert removed_key_ids == [200751]

    async def _assert_deleted() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is None, "expired pass must be deleted, not just flagged expired"

    asyncio.run(_assert_deleted())


def test_sweep_expired_requests_once_deletes_already_expired_pass_with_lingering_key(client):
    """Rows already marked "expired" whose Gate key was never removed (e.g. flagged by
    the startup cleanup) must still be deleted and have the Gate key removed."""
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    request_id = asyncio.run(_insert_active_courier_request(user_id, entry_point_id, 200771))

    async def _expire_and_flag() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            row.status = "expired"  # already flagged, but Gate key still present
            await session.commit()

    asyncio.run(_expire_and_flag())

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    original_integration = gate_event_worker.settings.gate_real_integration_enabled
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    gate_event_worker.settings.gate_real_integration_enabled = True
    try:
        removed = asyncio.run(gate_event_worker.sweep_expired_requests_once())
    finally:
        gate_client.remove_key = original_remove_key
        gate_event_worker.settings.gate_real_integration_enabled = original_integration

    assert removed == 1
    assert removed_key_ids == [200771]

    async def _assert_deleted() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is None

    asyncio.run(_assert_deleted())


def test_sweep_expired_requests_once_defers_when_users_window_is_open(client):
    """If staff currently has "Список пользователей" open, the sweep must skip the
    first cycle (within the deferral limit) — a manual "Добавить" click in that window
    has no protection while a removal is in flight and depends on the window being left
    alone.  The deferral only lasts up to _SWEEP_MAX_DEFER_SECONDS (see separate test).
    """
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    request_id = asyncio.run(_insert_active_courier_request(user_id, entry_point_id, 200781))

    async def _expire() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(_expire())

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    original_is_users_window_open = gate_client.is_users_window_open
    original_integration = gate_event_worker.settings.gate_real_integration_enabled
    original_defer_start = gate_event_worker._sweep_defer_start
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    gate_client.is_users_window_open = lambda: True
    gate_event_worker.settings.gate_real_integration_enabled = True
    gate_event_worker._sweep_defer_start = None  # ensure clean slate
    try:
        removed = asyncio.run(gate_event_worker.sweep_expired_requests_once())
    finally:
        gate_client.remove_key = original_remove_key
        gate_client.is_users_window_open = original_is_users_window_open
        gate_event_worker.settings.gate_real_integration_enabled = original_integration
        gate_event_worker._sweep_defer_start = original_defer_start

    assert removed == 0
    assert removed_key_ids == []

    async def _assert_not_deleted() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None, "deferred sweep must not delete the pass this cycle"

    asyncio.run(_assert_not_deleted())


def test_sweep_expired_requests_once_forces_sweep_after_max_deferral(client):
    """After _SWEEP_MAX_DEFER_SECONDS of continuous window-open deferral the sweep must
    run regardless — an indefinitely-stuck window (e.g. left open by a failed
    gate_bridge operation) must not prevent expired passes from ever being removed.
    """
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    request_id = asyncio.run(_insert_active_courier_request(user_id, entry_point_id, 200791))

    async def _expire() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(_expire())

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    original_is_users_window_open = gate_client.is_users_window_open
    original_integration = gate_event_worker.settings.gate_real_integration_enabled
    original_defer_start = gate_event_worker._sweep_defer_start
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    gate_client.is_users_window_open = lambda: True
    gate_event_worker.settings.gate_real_integration_enabled = True
    # Simulate that the window has been open for longer than the allowed limit
    gate_event_worker._sweep_defer_start = (
        time.monotonic() - gate_event_worker._SWEEP_MAX_DEFER_SECONDS - 1.0
    )
    try:
        removed = asyncio.run(gate_event_worker.sweep_expired_requests_once())
    finally:
        gate_client.remove_key = original_remove_key
        gate_client.is_users_window_open = original_is_users_window_open
        gate_event_worker.settings.gate_real_integration_enabled = original_integration
        gate_event_worker._sweep_defer_start = original_defer_start

    assert removed == 1, "sweep must run and delete the expired pass after max deferral exceeded"
    assert removed_key_ids == [200791], "Gate key must be removed even while window appears open"


def test_sweep_expired_requests_once_noop_when_integration_disabled(client):
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    request_id = asyncio.run(_insert_active_courier_request(user_id, entry_point_id, 200761))

    async def _expire() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(_expire())

    original_integration = gate_event_worker.settings.gate_real_integration_enabled
    gate_event_worker.settings.gate_real_integration_enabled = False
    try:
        removed = asyncio.run(gate_event_worker.sweep_expired_requests_once())
    finally:
        gate_event_worker.settings.gate_real_integration_enabled = original_integration

    assert removed == 0

    async def _assert_still_active() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            assert row.status == "active"

    asyncio.run(_assert_still_active())


def test_access_open_exit_does_not_complete_courier_request(client):
    headers, user_id = _create_user_and_login(client)
    exit_point_id = get_settings().gate_action_map["exit"]
    request_id = asyncio.run(_insert_active_courier_request(user_id, exit_point_id, 200601))

    removed_key_ids: list[int] = []
    original_remove_key = gate_client.remove_key
    gate_client.remove_key = lambda key_id: removed_key_ids.append(int(key_id)) or True
    try:
        opened = client.post("/api/access/open", headers=headers, json={"access_point_id": exit_point_id})
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


def test_access_open_entry_schedules_created_courier_vehicle_request(client):
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

    async def _active_courier_row() -> Request:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            rows = list(query.scalars().all())
            assert len(rows) == 1
            return rows[0]

    courier_row = asyncio.run(_active_courier_row())
    assert courier_row.key_type == "VehicleNumber"
    assert courier_row.contact_phone == phone_number
    opened_at = datetime.now(timezone.utc)
    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    assert opened.status_code == 200
    assert opened.json()["status"] == "success"

    async def _assert_courier_request_scheduled() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, courier_row.id)
            assert row is not None
            assert row.status == "active"
            assert row.cancelled_at is None
            assert row.contact_phone == phone_number
            assert row.expires_at is not None
            expires_at = row.expires_at
            normalized = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
            remaining = normalized - opened_at
            assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1)

    asyncio.run(_assert_courier_request_scheduled())


def test_gate_entry_event_schedules_vehicle_only_courier_pass(client):
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

    async def _active_courier_row() -> Request:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            rows = list(query.scalars().all())
            assert len(rows) == 1
            return rows[0]

    courier_row = asyncio.run(_active_courier_row())
    assert courier_row.key_type == "VehicleNumber"

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
                        "name": courier_row.key_value,
                        "user_ptr": courier_row.gate_key_id,
                    },
                    {
                        "index": 900002,
                        "event_type": 1,
                        "event_code": 8,
                        "access_point_id": entry_point_id,
                        "unit": "Считыватель въезд GSM",
                        "message": "Проход совершен",
                        "name": phone_number,
                        "user_ptr": courier_row.gate_key_id,
                    },
                ],
            )

    event_at = datetime.now(timezone.utc)
    scheduled_count = asyncio.run(_process_gate_event())
    assert scheduled_count == 1

    async def _assert_courier_event_schedule() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, courier_row.id)
            assert row is not None
            assert row.status == "active"
            assert row.expires_at is not None
            expires_at = row.expires_at
            normalized = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
            remaining = normalized - event_at
            assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1)

            log_query = await session.execute(
                select(AccessEventLog).where(AccessEventLog.request_id == "gate-entry-900001")
            )
            log = log_query.scalar_one()
            assert log.action == "courier_gate_entry"
            assert log.details["courier_scheduled_request_ids"] == [courier_row.id]
            assert log.details["courier_cleanup"] == "scheduled_after_entry"

    asyncio.run(_assert_courier_event_schedule())


def test_gate_entry_event_schedules_courier_on_passage_completed_code_8(client):
    """A camera entry emits code 2 (granted) and code 8 (passage completed).
    Code 8 alone must still start the courier TTL countdown."""
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    create_response = client.post(
        "/passes",
        headers=headers,
        json={
            "carNumber": f"C8{uuid4().hex[:5]}",
            "plotNumber": "81",
            "phoneNumber": f"7944{str(uuid4().int)[:7]}",
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "isPermanent": False,
            "isCourier": True,
        },
    )
    assert create_response.status_code == 200

    async def _courier_row() -> Request:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request).where(
                    Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True)
                )
            )
            rows = list(query.scalars().all())
            assert len(rows) == 1
            return rows[0]

    courier_row = asyncio.run(_courier_row())

    async def _process() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 910008,
                        "event_type": 1,
                        "event_code": 8,
                        "access_point_id": entry_point_id,
                        "unit": "Камера Въезда",
                        "message": "Проход совершен",
                        "name": courier_row.key_value,
                        "user_ptr": courier_row.gate_key_id,
                    },
                ],
            )

    event_at = datetime.now(timezone.utc)
    assert asyncio.run(_process()) == 1

    async def _assert_scheduled() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, courier_row.id)
            assert row is not None
            assert row.expires_at is not None
            normalized = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
            remaining = normalized - event_at
            assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1)

    asyncio.run(_assert_scheduled())


def test_gate_entry_event_matches_courier_by_plate_when_user_ptr_drifted(client):
    """If the stored gate_key_id no longer matches the camera event's user_ptr
    (the vehicle user was recreated), the courier pass must still be matched by
    its vehicle plate."""
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    plate = f"P{uuid4().hex[:6].upper()}"
    create_response = client.post(
        "/passes",
        headers=headers,
        json={
            "carNumber": plate,
            "plotNumber": "82",
            "phoneNumber": f"7955{str(uuid4().int)[:7]}",
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "isPermanent": False,
            "isCourier": True,
        },
    )
    assert create_response.status_code == 200

    async def _courier_row() -> Request:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request).where(
                    Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True)
                )
            )
            rows = list(query.scalars().all())
            assert len(rows) == 1
            return rows[0]

    courier_row = asyncio.run(_courier_row())
    drifted_user_ptr = int(courier_row.gate_key_id or 0) + 777777

    async def _process() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 910009,
                        "event_type": 1,
                        "event_code": 2,
                        "access_point_id": entry_point_id,
                        "unit": "Камера Въезда",
                        "message": "Проход по ключу разрешен",
                        # Gate reports the plate (key_value) but a different user_ptr.
                        "key_value": courier_row.key_value,
                        "name": f"{courier_row.key_value}   Гость",
                        "user_ptr": drifted_user_ptr,
                    },
                ],
            )

    event_at = datetime.now(timezone.utc)
    assert asyncio.run(_process()) == 1

    async def _assert_scheduled() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, courier_row.id)
            assert row is not None
            assert row.expires_at is not None
            normalized = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
            remaining = normalized - event_at
            assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1)

    asyncio.run(_assert_scheduled())


def test_gate_entry_event_schedules_vehicle_only_courier_pass_when_reader_looks_like_entry(client):
    headers, user_id = _create_user_and_login(client)
    wicket_point_id = get_settings().gate_action_map["wicket_admin"]
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

    async def _active_courier_row() -> Request:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            rows = list(query.scalars().all())
            assert len(rows) == 1
            return rows[0]

    courier_row = asyncio.run(_active_courier_row())
    assert courier_row.key_type == "VehicleNumber"
    original_expires_at = courier_row.expires_at

    async def _process_non_entry_event() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 900101,
                        "event_type": 1,
                        "event_code": 2,
                        "access_point_id": wicket_point_id,
                        "unit": "Камера Въезда",
                        "message": "Проход по ключу разрешен",
                        "name": courier_row.key_value,
                        "user_ptr": courier_row.gate_key_id,
                    }
                ],
            )

    scheduled_count = asyncio.run(_process_non_entry_event())
    assert scheduled_count == 1

    async def _assert_entry_like_event_schedule() -> None:
        async with SessionLocal() as session:
            row = await session.get(Request, courier_row.id)
            assert row is not None
            assert row.status == "active"
            assert row.expires_at is not None
            assert row.expires_at != original_expires_at

            log_query = await session.execute(
                select(AccessEventLog).where(AccessEventLog.request_id == "gate-entry-900101")
            )
            log = log_query.scalar_one()
            assert log.action == "courier_gate_entry"
            assert log.details["courier_scheduled_request_ids"] == [courier_row.id]

    asyncio.run(_assert_entry_like_event_schedule())


def test_gate_entry_event_continues_when_access_point_sync_temporarily_fails(client, monkeypatch):
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    phone_number = f"7934{str(uuid4().int)[:7]}"
    create_response = client.post(
        "/passes",
        headers=headers,
        json={
            "carNumber": f"CAM{uuid4().hex[:5]}",
            "plotNumber": "81",
            "phoneNumber": phone_number,
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "isPermanent": False,
            "isCourier": True,
        },
    )
    assert create_response.status_code == 200

    async def _active_courier_row() -> Request:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            rows = list(query.scalars().all())
            assert len(rows) == 1
            return rows[0]

    courier_row = asyncio.run(_active_courier_row())

    async def _broken_sync(_session) -> None:
        raise RuntimeError("temporary Gate MDB snapshot failure")

    monkeypatch.setattr("backend.app.services.access.sync_access_points", _broken_sync)

    async def _process_gate_event() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 900201,
                        "event_type": 1,
                        "event_code": 2,
                        "access_point_id": entry_point_id,
                        "unit": "РЎС‡РёС‚С‹РІР°С‚РµР»СЊ РІСЉРµР·Рґ GSM",
                        "message": "РџСЂРѕС…РѕРґ РїРѕ РєР»СЋС‡Сѓ СЂР°Р·СЂРµС€РµРЅ",
                        "name": courier_row.key_value,
                        "user_ptr": courier_row.gate_key_id,
                    }
                ],
            )

    scheduled_count = asyncio.run(_process_gate_event())
    assert scheduled_count == 1


def test_vehicle_only_courier_passes_do_not_create_phone_rows(client):
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

    async def _courier_rows() -> list[Request]:
        async with SessionLocal() as session:
            query = await session.execute(
                select(Request)
                .where(Request.resident_id == user_id, Request.status == "active", Request.is_courier.is_(True))
                .order_by(Request.id)
            )
            return list(query.scalars().all())

    rows = asyncio.run(_courier_rows())
    assert len(rows) == 1
    assert rows[0].key_type == "VehicleNumber"
    assert rows[0].contact_phone == phone_number
    return

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


# ---------------------------------------------------------------------------
# _cooldown_message — gender agreement of the demonstrative pronoun
# ---------------------------------------------------------------------------


def test_cooldown_message_uses_feminine_pronoun_for_wicket():
    from backend.app.services.access import _cooldown_message

    wicket = AccessPoint(id=9101, name="Калитка Север", code="w-9101", type="wicket", is_active=True)
    message = _cooldown_message(wicket, 7)
    assert "этой калитки" in message
    assert "этого" not in message


def test_cooldown_message_uses_masculine_pronoun_for_barrier():
    from backend.app.services.access import _cooldown_message

    barrier = AccessPoint(id=9102, name="Шлагбаум Въезд", code="b-9102", type="barrier_entry", is_active=True)
    message = _cooldown_message(barrier, 5)
    assert "этого шлагбаума" in message
    assert "этой" not in message


def test_request_priority_at_entry_prefers_personal_over_courier():
    """At barrier_entry, a personal pass must rank better (lower tuple) than a courier pass.

    Regression test: before the fix, temporary courier passes ranked *lower* (= won)
    over permanent personal passes because permanent_rank(temp)=0 < permanent_rank(perm)=1
    and courier_rank was identical for everyone at entry.  This caused _schedule_courier_
    requests_after_entry to fire when the resident opened the barrier for themselves.
    """
    from types import SimpleNamespace

    from backend.app.services.access import _request_priority

    now = datetime.now(timezone.utc)
    courier_pass = SimpleNamespace(is_permanent=False, is_courier=True, created_at=now)
    personal_pass = SimpleNamespace(is_permanent=True, is_courier=False, created_at=now)

    entry_courier = _request_priority(courier_pass, prefer_courier=False)
    entry_personal = _request_priority(personal_pass, prefer_courier=False)
    assert entry_personal < entry_courier, (
        f"At entry: personal {entry_personal} must rank better (lower) than courier {entry_courier}"
    )

    exit_courier = _request_priority(courier_pass, prefer_courier=True)
    exit_personal = _request_priority(personal_pass, prefer_courier=True)
    assert exit_courier < exit_personal, (
        f"At exit: courier {exit_courier} must rank better (lower) than personal {exit_personal}"
    )


def test_access_open_entry_prefers_personal_pass_over_courier_when_both_present(client):
    """When a resident has both a permanent personal pass and a courier pass,
    pressing 'open barrier' at entry must NOT trigger the courier 2-hour countdown.

    Regression test: before the fix, the courier pass was selected as primary at entry
    (because its permanent_rank=0 beat the personal pass's permanent_rank=1), causing
    _schedule_courier_requests_after_entry to fire and shift expires_at to now+2h.
    """
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]

    # Insert both passes: courier temp (gate_key_id=200701) + personal permanent (200702)
    courier_id = asyncio.run(_insert_active_courier_request(user_id, entry_point_id, 200701))
    asyncio.run(_insert_active_permanent_request(user_id, entry_point_id, 200702))

    opened_at = datetime.now(timezone.utc)
    opened = client.post("/api/access/open", headers=headers, json={"access_point_id": entry_point_id})
    assert opened.status_code == 200
    assert opened.json()["status"] == "success"

    async def _assert_courier_timer_did_not_fire() -> None:
        async with SessionLocal() as session:
            courier_row = await session.get(Request, courier_id)
            assert courier_row is not None
            # If the courier timer fired, expires_at would be ~2 h from now.
            # Original expiry was ~1 h from creation → must still be < 1 h 30 min.
            expires_at = courier_row.expires_at
            normalized = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
            remaining = normalized - opened_at
            assert remaining < timedelta(hours=1, minutes=30), (
                f"Courier 2-hour timer fired unexpectedly when personal pass was present: "
                f"remaining={remaining}"
            )

    asyncio.run(_assert_courier_timer_did_not_fire())


# ---------------------------------------------------------------------------
# Companion-pairing fix: vehicle → vehicle must NOT be paired; only vehicle ↔ phone
# ---------------------------------------------------------------------------


async def _insert_courier_vehicle_request_with_phone(
    user_id: int, access_point_id: int, gate_key_id: int, *, contact_phone: str, pass_kind: str = "courier"
) -> int:
    """Insert an active courier-type VehicleNumber pass with an explicit contact_phone."""
    async with SessionLocal() as session:
        row = Request(
            resident_id=user_id,
            key_type="VehicleNumber",
            key_value=f"VH{uuid4().hex[:6].upper()}",
            gate_key_id=gate_key_id,
            access_point_ids=[access_point_id],
            is_permanent=False,
            is_courier=True,
            pass_kind=pass_kind,
            contact_phone=contact_phone,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0),
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        request_id = int(row.id)
        await session.commit()
        return request_id


async def _insert_courier_phone_request(
    user_id: int, access_point_id: int, gate_key_id: int, *, phone_number: str
) -> int:
    """Insert an active courier-type Phone pass."""
    async with SessionLocal() as session:
        row = Request(
            resident_id=user_id,
            key_type="Phone",
            key_value=phone_number,
            gate_key_id=gate_key_id,
            access_point_ids=[access_point_id],
            is_permanent=False,
            is_courier=True,
            contact_phone=phone_number,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0),
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        request_id = int(row.id)
        await session.commit()
        return request_id


def test_courier_entry_timer_does_not_bleed_to_same_phone_courier_vehicle_pass(client):
    """Two courier-type vehicle passes (e.g., courier + taxi) that belong to the same
    account and share the same contact_phone must NOT have their timers linked.

    Regression: _courier_companion_candidates paired vehicle→vehicle via contact_phone,
    so when either car drove through entry, BOTH passes got expires_at = now+2h.
    After the fix only the triggered pass should be updated.
    """
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    shared_phone = f"+7800{str(uuid4().int)[:7]}"

    courier_id = asyncio.run(
        _insert_courier_vehicle_request_with_phone(
            user_id, entry_point_id, 400001, contact_phone=shared_phone, pass_kind="courier"
        )
    )
    taxi_id = asyncio.run(
        _insert_courier_vehicle_request_with_phone(
            user_id, entry_point_id, 400002, contact_phone=shared_phone, pass_kind="taxi"
        )
    )

    # Record taxi pass original expiry before the gate event.
    async def _get_expires_at(request_id: int) -> datetime:
        async with SessionLocal() as session:
            row = await session.get(Request, request_id)
            assert row is not None
            return row.expires_at  # type: ignore[return-value]

    taxi_original_expires = asyncio.run(_get_expires_at(taxi_id))

    async def _process_courier_entry() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 400101,
                        "event_type": 1,
                        "event_code": 2,
                        "access_point_id": entry_point_id,
                        "unit": "Считыватель въезд GSM",
                        "message": "Проход по ключу разрешен",
                        "user_ptr": 400001,
                    }
                ],
            )

    event_at = datetime.now(timezone.utc)
    scheduled_count = asyncio.run(_process_courier_entry())
    assert scheduled_count == 1, "Only the triggering pass should be scheduled"

    async def _assert_only_courier_pass_updated() -> None:
        async with SessionLocal() as session:
            courier_row = await session.get(Request, courier_id)
            taxi_row = await session.get(Request, taxi_id)
            assert courier_row is not None
            assert taxi_row is not None

            # Courier pass must have the new 2-hour expiry.
            courier_expires = courier_row.expires_at
            normalized_courier = (
                courier_expires.replace(tzinfo=timezone.utc) if courier_expires.tzinfo is None else courier_expires
            )
            remaining = normalized_courier - event_at
            assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1), (
                f"Courier pass should have ~2h expiry after entry, got remaining={remaining}"
            )

            # Taxi pass must NOT have been touched — its expiry must be unchanged.
            taxi_expires = taxi_row.expires_at
            assert taxi_expires == taxi_original_expires, (
                f"Taxi pass expires_at must not change when courier vehicle enters: "
                f"original={taxi_original_expires}, after_event={taxi_expires}"
            )

    asyncio.run(_assert_only_courier_pass_updated())


def test_courier_vehicle_entry_timer_propagates_to_companion_phone_pass(client):
    """When a courier has both a VehicleNumber pass and a Phone pass sharing the same
    phone number, and the vehicle drives through entry, BOTH passes must get the 2-hour
    timer set — a phone+vehicle pair represent the same physical courier trip.
    """
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    courier_phone = f"+7900{str(uuid4().int)[:7]}"

    vehicle_id = asyncio.run(
        _insert_courier_vehicle_request_with_phone(
            user_id, entry_point_id, 400101, contact_phone=courier_phone, pass_kind="courier"
        )
    )
    phone_id = asyncio.run(
        _insert_courier_phone_request(user_id, entry_point_id, 400102, phone_number=courier_phone)
    )

    async def _process_vehicle_entry() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 400201,
                        "event_type": 1,
                        "event_code": 2,
                        "access_point_id": entry_point_id,
                        "unit": "Считыватель въезд GSM",
                        "message": "Проход по ключу разрешен",
                        "user_ptr": 400101,
                    }
                ],
            )

    event_at = datetime.now(timezone.utc)
    scheduled_count = asyncio.run(_process_vehicle_entry())
    assert scheduled_count == 2, "Vehicle + phone companion must both be scheduled (2 passes)"

    async def _assert_both_passes_updated() -> None:
        async with SessionLocal() as session:
            vehicle_row = await session.get(Request, vehicle_id)
            phone_row = await session.get(Request, phone_id)
            assert vehicle_row is not None
            assert phone_row is not None

            for label, row in [("vehicle", vehicle_row), ("phone", phone_row)]:
                expires = row.expires_at
                normalized = expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires
                remaining = normalized - event_at
                assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1), (
                    f"{label} pass should have ~2h expiry after vehicle entry, got remaining={remaining}"
                )

    asyncio.run(_assert_both_passes_updated())


def test_courier_phone_entry_timer_propagates_to_companion_vehicle_pass(client):
    """When a courier triggers entry via their Phone pass, the companion VehicleNumber pass
    (same contact_phone) must also receive the 2-hour timer — the phone↔vehicle pair share
    the entry TTL in both trigger directions.
    """
    headers, user_id = _create_user_and_login(client)
    entry_point_id = get_settings().gate_action_map["entry"]
    courier_phone = f"+7901{str(uuid4().int)[:7]}"

    phone_id = asyncio.run(
        _insert_courier_phone_request(user_id, entry_point_id, 400301, phone_number=courier_phone)
    )
    vehicle_id = asyncio.run(
        _insert_courier_vehicle_request_with_phone(
            user_id, entry_point_id, 400302, contact_phone=courier_phone, pass_kind="courier"
        )
    )

    async def _process_phone_entry() -> int:
        async with SessionLocal() as session:
            return await process_courier_gate_entry_events(
                session,
                [
                    {
                        "index": 400301,
                        "event_type": 1,
                        "event_code": 2,
                        "access_point_id": entry_point_id,
                        "unit": "Считыватель въезд GSM",
                        "message": "Проход по ключу разрешен",
                        "user_ptr": 400301,
                    }
                ],
            )

    event_at = datetime.now(timezone.utc)
    scheduled_count = asyncio.run(_process_phone_entry())
    assert scheduled_count == 2, "Phone + vehicle companion must both be scheduled (2 passes)"

    async def _assert_both_passes_updated() -> None:
        async with SessionLocal() as session:
            phone_row = await session.get(Request, phone_id)
            vehicle_row = await session.get(Request, vehicle_id)
            assert phone_row is not None
            assert vehicle_row is not None

            for label, row in [("phone", phone_row), ("vehicle", vehicle_row)]:
                expires = row.expires_at
                normalized = expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires
                remaining = normalized - event_at
                assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1), (
                    f"{label} pass should have ~2h expiry after phone entry, got remaining={remaining}"
                )

    asyncio.run(_assert_both_passes_updated())
