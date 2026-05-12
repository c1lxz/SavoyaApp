from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models import AccessEventLog, AccessPoint, Request, User
from backend.app.services.auth import hash_password
from backend.app.services.gate import GateOpenResult
from backend.app.services.vehicle_camera_simulator import (
    VehicleCameraSimulationError,
    build_simulated_gate_pass_event,
    resolve_target_access_point,
    simulate_vehicle_camera_open,
)


def test_build_simulated_gate_pass_event_matches_gate_pass_shape() -> None:
    event_time = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)

    event = build_simulated_gate_pass_event(
        access_point_id=19,
        user_ptr=7001,
        key_value="A123AA77",
        access_point_name="Camera Entry",
        event_time=event_time,
        event_index=900123,
    )

    assert event == {
        "index": 900123,
        "time": event_time.isoformat(),
        "event_type": 1,
        "event_code": 2,
        "access_point_id": 19,
        "unit": "Camera Entry",
        "message": "Simulated camera recognition by vehicle number",
        "name": "A123AA77",
        "user_ptr": 7001,
    }


def test_resolve_target_access_point_rejects_unavailable_point() -> None:
    with pytest.raises(VehicleCameraSimulationError, match="Allowed ids: \\[20\\]"):
        resolve_target_access_point(action="entry", allowed_access_point_ids=[20])


async def _seed_vehicle_request(*, access_point_id: int, key_value: str, gate_key_id: int) -> tuple[int, datetime]:
    async with SessionLocal() as session:
        user = User(
            phone=f"+7999{str(uuid4().int)[:7]}",
            login=f"vehicle_{uuid4().hex[:8]}",
            password_hash=hash_password("demo123"),
            name="Vehicle Tester",
            apartment="1",
            plot_number="1",
            is_admin=False,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        point = await session.get(AccessPoint, access_point_id)
        if point is None:
            session.add(
                AccessPoint(
                    id=access_point_id,
                    name="Entry Barrier",
                    code=f"entry-{access_point_id}",
                    type="barrier_entry",
                    is_active=True,
                )
            )
        else:
            point.name = "Entry Barrier"
            point.code = point.code or f"entry-{access_point_id}"
            point.type = "barrier_entry"
            point.is_active = True

        expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
        request = Request(
            resident_id=user.id,
            key_type="VehicleNumber",
            key_value=key_value,
            gate_key_id=gate_key_id,
            access_point_ids=[access_point_id],
            is_permanent=False,
            is_courier=True,
            contact_phone="+79991234567",
            expires_at=expires_at,
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        session.add(request)
        await session.flush()
        request_id = int(request.id)
        await session.commit()
        return request_id, expires_at


def test_simulate_vehicle_camera_open_uses_backend_request_and_processes_event(monkeypatch) -> None:
    point_id = get_settings().gate_action_map["entry"]
    request_id, original_expires_at = asyncio.run(
        _seed_vehicle_request(access_point_id=point_id, key_value="A123AA77", gate_key_id=771001)
    )

    monkeypatch.setattr(
        "backend.app.services.vehicle_camera_simulator.gate_client.open_access_point",
        lambda access_point_id, key_external_id=None: GateOpenResult(
            success=True,
            message=f"Opened {access_point_id}",
            details={"transport": "gateterm_ui", "key_external_id": key_external_id},
        ),
    )

    async def _run() -> dict:
        async with SessionLocal() as session:
            result = await simulate_vehicle_camera_open(session, vehicle_number="A 123-AA 77")
            return result.as_dict()

    result = asyncio.run(_run())

    assert result["open_success"] is True
    assert result["backend_request_id"] == request_id
    assert result["backend_gate_key_id"] == 771001
    assert result["external_key_id"] == "771001"
    assert result["simulated_camera_event_processed"] is True
    assert result["courier_scheduled_count"] == 1
    assert result["simulated_camera_event"]["event_code"] == 2

    async def _assert_state() -> None:
        async with SessionLocal() as session:
            request = await session.get(Request, request_id)
            assert request is not None
            assert request.expires_at is not None
            assert request.expires_at != original_expires_at

            log_query = await session.execute(
                select(AccessEventLog).where(
                    AccessEventLog.request_id == f"gate-entry-{result['simulated_camera_event']['index']}"
                )
            )
            log = log_query.scalar_one()
            assert log.action == "courier_gate_entry"
            assert log.details["gate_event"]["user_ptr"] == 771001

    asyncio.run(_assert_state())


def test_simulate_vehicle_camera_open_matches_existing_cyrillic_vehicle_request(monkeypatch) -> None:
    point_id = get_settings().gate_action_map["entry"]
    request_id, _ = asyncio.run(
        _seed_vehicle_request(access_point_id=point_id, key_value="А123АА77", gate_key_id=771002)
    )

    monkeypatch.setattr(
        "backend.app.services.vehicle_camera_simulator.gate_client.open_access_point",
        lambda access_point_id, key_external_id=None: GateOpenResult(
            success=True,
            message=f"Opened {access_point_id}",
            details={"transport": "gateterm_ui", "key_external_id": key_external_id},
        ),
    )

    async def _run() -> dict:
        async with SessionLocal() as session:
            result = await simulate_vehicle_camera_open(session, vehicle_number="A123AA77")
            return result.as_dict()

    result = asyncio.run(_run())

    assert result["open_success"] is True
    assert result["backend_request_id"] == request_id
    assert result["backend_gate_key_id"] == 771002
    assert result["vehicle_number"] == "A123AA77"


def test_simulate_vehicle_camera_open_can_fallback_to_gate_permissions(monkeypatch) -> None:
    point_id = get_settings().gate_action_map["entry"]

    monkeypatch.setattr(
        "backend.app.services.vehicle_camera_simulator.gate_client.get_key_permissions",
        lambda key_external_id: [{"access_point_id": point_id, "access_point_name": "entry"}],
    )
    monkeypatch.setattr(
        "backend.app.services.vehicle_camera_simulator.gate_client.open_access_point",
        lambda access_point_id, key_external_id=None: GateOpenResult(
            success=True,
            message="Opened via Gate lookup",
            details={"transport": "gateterm_ui", "key_external_id": key_external_id},
        ),
    )

    async def _run() -> dict:
        async with SessionLocal() as session:
            result = await simulate_vehicle_camera_open(session, vehicle_number="B123BB77")
            return result.as_dict()

    result = asyncio.run(_run())

    assert result["open_success"] is True
    assert result["backend_request_id"] is None
    assert result["external_key_id"] == "B123BB77"
    assert result["simulated_camera_event_processed"] is False
    assert any("Gate" in warning for warning in result["warnings"])
