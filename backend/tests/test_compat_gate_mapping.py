from __future__ import annotations

from backend.app.routers import compatibility
from backend.app.schemas import CompatCreatePassPayload


def test_runtime_gate_action_map_infers_real_reader_ids(monkeypatch):
    monkeypatch.setattr(compatibility.settings, "gate_real_integration_enabled", True)
    monkeypatch.setattr(
        compatibility.settings,
        "gate_action_map_json",
        '{"entry":1,"exit":2,"wicket_north":3,"wicket_lake":4,"wicket_admin":5,"wicket_forest":6}',
    )
    monkeypatch.setattr(
        compatibility.gate_client,
        "get_access_points",
        lambda: [
            {"id": 19, "name": "Камера Въезда"},
            {"id": 20, "name": "Камера Выезда"},
            {"id": 15, "name": "Считыватель Северная калитка 1"},
            {"id": 23, "name": "Вход озеро"},
            {"id": 17, "name": "Считыватель калитка у администрации"},
            {"id": 21, "name": "Вход Лес"},
        ],
    )

    assert compatibility._runtime_gate_action_map() == {
        "entry": 19,
        "exit": 20,
        "wicket_north": 15,
        "wicket_lake": 23,
        "wicket_admin": 17,
        "wicket_forest": 21,
    }


def test_runtime_default_access_point_ids_fallbacks_to_real_points(monkeypatch):
    monkeypatch.setattr(compatibility.settings, "gate_real_integration_enabled", True)
    monkeypatch.setattr(compatibility.settings, "default_access_point_ids_json", "[1,2,3,4,5,6]")
    monkeypatch.setattr(
        compatibility.gate_client,
        "get_access_points",
        lambda: [
            {"id": 15, "name": "Считыватель Северная калитка 1"},
            {"id": 17, "name": "Считыватель калитка 1"},
            {"id": 19, "name": "Камера Въезда"},
        ],
    )

    assert compatibility._runtime_default_access_point_ids() == [15, 17, 19]


def test_runtime_gate_action_map_detects_admin_wicket_from_kalitka_1(monkeypatch):
    monkeypatch.setattr(compatibility.settings, "gate_real_integration_enabled", True)
    monkeypatch.setattr(
        compatibility.settings,
        "gate_action_map_json",
        '{"entry":19,"exit":20,"wicket_north":15,"wicket_lake":23,"wicket_admin":17,"wicket_forest":21}',
    )
    monkeypatch.setattr(
        compatibility.gate_client,
        "get_access_points",
        lambda: [
            {"id": 17, "name": "Считыватель калитка 1"},
        ],
    )

    assert compatibility._runtime_gate_action_map()["wicket_admin"] == 17


def test_runtime_gsm_access_point_ids_prefers_explicit_config(monkeypatch):
    monkeypatch.setattr(compatibility.settings, "gate_real_integration_enabled", True)
    monkeypatch.setattr(compatibility.settings, "gsm_access_point_ids_json", "[70]")
    monkeypatch.setattr(
        compatibility.gate_client,
        "get_access_points",
        lambda: [
            {"id": 15, "name": "Entry Camera"},
            {"id": 70, "name": "Reader 70"},
            {"id": 71, "name": "Gate Terminal Entry"},
        ],
    )

    assert compatibility._runtime_gsm_access_point_ids() == [70]


def test_runtime_gsm_access_point_ids_detects_terminal_hints_when_config_is_empty(monkeypatch):
    monkeypatch.setattr(compatibility.settings, "gate_real_integration_enabled", True)
    monkeypatch.setattr(compatibility.settings, "gsm_access_point_ids_json", "[]")
    monkeypatch.setattr(
        compatibility.gate_client,
        "get_access_points",
        lambda: [
            {"id": 15, "name": "Entry Camera"},
            {"id": 70, "name": "Reader 70"},
            {"id": 71, "name": "Gate Terminal Entry"},
        ],
    )

    assert compatibility._runtime_gsm_access_point_ids() == [71]


def test_build_compat_create_payloads_does_not_create_gsm_phone_pass(monkeypatch):
    monkeypatch.setattr(compatibility, "_runtime_default_access_point_ids", lambda: [15, 17, 19])
    monkeypatch.setattr(compatibility, "_runtime_gsm_access_point_ids", lambda: [70, 71])

    payload = CompatCreatePassPayload(
        carNumber="A123AA77",
        plotNumber="25",
        phoneNumber="+79991234567",
        expiresAt=None,
        isPermanent=True,
        isCourier=False,
    )

    rows = compatibility._build_compat_create_payloads(
        payload,
        contact_phone_number=payload.phoneNumber,
    )

    assert len(rows) == 1
    assert rows[0].key_type == "VehicleNumber"
    assert rows[0].access_point_ids == [15, 17, 19]
