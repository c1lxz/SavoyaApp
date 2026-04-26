from __future__ import annotations

import pytest

from backend.app.services import gate


@pytest.mark.parametrize(
    ("real_integration_enabled", "key_type", "expected_actions"),
    [
        (True, "VehicleNumber", ["add_permanent_key", "post_sync_vehicle_key"]),
        (True, "Phone", ["add_permanent_key"]),
        (False, "VehicleNumber", []),
    ],
)
def test_add_permanent_key_vehicle_post_sync_only_for_real_integration(
    monkeypatch,
    real_integration_enabled: bool,
    key_type: str,
    expected_actions: list[str],
) -> None:
    client = gate.GateClient()
    actions: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", real_integration_enabled)

    def _fake_run_bridge(action: str, payload=None):
        actions.append(action)
        if action == "post_sync_vehicle_key":
            return {"transport": "gateterm_ui", "user_ptr": 321}
        return 321

    monkeypatch.setattr(client, "_run_bridge", _fake_run_bridge)

    result = client.add_permanent_key(
        key_type=key_type,
        key_value="A123AA77" if key_type == "VehicleNumber" else "+79991234567",
        phone_number="+79991234567",
        access_point_ids=[1],
        resident_name="Test User",
    )

    assert result == (321 if real_integration_enabled else 10001)
    assert actions == expected_actions


def test_add_permanent_key_removes_created_vehicle_key_when_post_sync_fails(monkeypatch) -> None:
    client = gate.GateClient()
    actions: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", True)
    monkeypatch.setattr(gate.settings, "gate_vehicle_post_sync_required", True)

    def _fake_run_bridge(action: str, payload=None):
        actions.append(action)
        if action == "add_permanent_key":
            return 321
        if action == "post_sync_vehicle_key":
            raise RuntimeError("post-sync failed")
        if action == "remove_key":
            return True
        raise AssertionError(action)

    monkeypatch.setattr(client, "_run_bridge", _fake_run_bridge)

    with pytest.raises(RuntimeError, match="post-sync failed"):
        client.add_permanent_key(
            key_type="VehicleNumber",
            key_value="A123AA77",
            phone_number="+79991234567",
            access_point_ids=[1],
            resident_name="Test User",
        )

    assert actions == ["add_permanent_key", "post_sync_vehicle_key", "remove_key"]


def test_add_permanent_key_keeps_created_vehicle_key_when_post_sync_fails_in_best_effort_mode(monkeypatch) -> None:
    client = gate.GateClient()
    actions: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", True)
    monkeypatch.setattr(gate.settings, "gate_vehicle_post_sync_required", False)

    def _fake_run_bridge(action: str, payload=None):
        actions.append(action)
        if action == "add_permanent_key":
            return 321
        if action == "post_sync_vehicle_key":
            raise RuntimeError("post-sync failed")
        raise AssertionError(action)

    monkeypatch.setattr(client, "_run_bridge", _fake_run_bridge)

    result = client.add_permanent_key(
        key_type="VehicleNumber",
        key_value="A123AA77",
        phone_number="+79991234567",
        access_point_ids=[1],
        resident_name="Test User",
    )

    assert result == 321
    assert actions == ["add_permanent_key", "post_sync_vehicle_key"]
