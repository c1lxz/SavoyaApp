from __future__ import annotations

from backend.app.routers import compatibility


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
