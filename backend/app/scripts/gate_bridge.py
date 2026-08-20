from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.app.scripts import gate_runtime


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _call(action: str, payload: dict) -> object:
    if action == "add_temporary_key":
        return gate_runtime.add_temporary_key(
            key_type=str(payload["key_type"]),
            key_value=str(payload["key_value"]),
            phone_number=str(payload["phone_number"]) if payload.get("phone_number") is not None else None,
            expires_at=_parse_datetime(str(payload["expires_at"])),
            access_point_ids=[int(item) for item in payload["access_point_ids"]],
            resident_name=str(payload.get("resident_name") or "Resident"),
            plot_number=str(payload["plot_number"]) if payload.get("plot_number") is not None else None,
        )
    if action == "add_permanent_key":
        return gate_runtime.add_permanent_key(
            key_type=str(payload["key_type"]),
            key_value=str(payload["key_value"]),
            phone_number=str(payload["phone_number"]) if payload.get("phone_number") is not None else None,
            access_point_ids=[int(item) for item in payload["access_point_ids"]],
            resident_name=str(payload.get("resident_name") or "Resident"),
            plot_number=str(payload["plot_number"]) if payload.get("plot_number") is not None else None,
        )
    if action == "add_phone_permanent_key_via_ui":
        return gate_runtime.add_phone_permanent_key_via_gateterm_ui(
            key_value=str(payload["key_value"]),
            phone_number=str(payload["phone_number"]) if payload.get("phone_number") is not None else None,
            access_point_ids=[int(item) for item in payload["access_point_ids"]],
            resident_name=str(payload.get("resident_name") or "Resident"),
            plot_number=str(payload["plot_number"]) if payload.get("plot_number") is not None else None,
        )
    if action == "remove_key":
        return gate_runtime.remove_key(int(payload["key_id"]))
    if action == "resolve_key_id":
        return gate_runtime.resolve_key_id(str(payload["external_key_id"]))
    if action == "get_access_points":
        return gate_runtime.get_access_points()
    if action == "is_users_window_open":
        return gate_runtime.is_gateterm_users_window_open()
    if action == "get_recent_events":
        return gate_runtime.get_recent_events(limit=int(payload.get("limit") or 100))
    if action == "repair_user_display_names":
        return gate_runtime.repair_user_display_names()
    if action == "repair_phone_identity_rows":
        return gate_runtime.repair_phone_identity_rows()
    if action == "repair_vehicle_number_u":
        return gate_runtime.repair_vehicle_number_u()
    if action == "repair_vehicle_visual_numbers":
        return gate_runtime.repair_vehicle_visual_numbers(limit=int(payload.get("limit") or 50))
    if action == "get_key_permissions":
        return gate_runtime.get_key_permissions(str(payload["external_key_id"]))
    if action == "list_vehicle_keys_by_phone":
        return gate_runtime.list_vehicle_keys_by_phone(str(payload["phone_number"]))
    if action == "list_vehicle_keys_by_name":
        return gate_runtime.list_vehicle_keys_by_name(str(payload["resident_name"]))
    if action == "list_keys_by_phone":
        return gate_runtime.list_keys_by_phone(str(payload["phone_number"]))
    if action == "get_wiegand_credentials":
        return gate_runtime.get_wiegand_credentials(str(payload["external_key_id"]))
    if action == "post_sync_phone_key":
        return gate_runtime.post_sync_phone_key(int(payload["key_id"]))
    if action == "post_sync_vehicle_key":
        return gate_runtime.post_sync_vehicle_key(int(payload["key_id"]))
    if action == "open_access_point":
        return gate_runtime.open_access_point(
            access_point_id=int(payload["access_point_id"]),
            external_key_id=str(payload["external_key_id"]) if payload.get("external_key_id") is not None else None,
        )
    raise ValueError(f"Unsupported gate bridge action: {action}")


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "Missing gate bridge action"}, ensure_ascii=False))
        return 2

    action = sys.argv[1]
    raw_payload = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read()
    payload = json.loads(raw_payload) if str(raw_payload or "").strip() else {}

    # FIX: hold a lock file for the duration of any UI-mutating action so that
    # gateterm_users_guard.py backs off and does not race gate_bridge for GateTerm's UI.
    # Racing causes VB6 Error 91 ("Object variable or With block variable not set") because
    # both processes try to open the "Поиск пользователя" search dialog simultaneously.
    _UI_MUTATING_ACTIONS = frozenset({
        "add_temporary_key", "add_permanent_key", "add_phone_permanent_key_via_ui",
        "remove_key", "post_sync_vehicle_key", "post_sync_phone_key", "open_access_point",
        "repair_phone_identity_rows", "repair_user_display_names",
        "repair_vehicle_number_u", "repair_vehicle_visual_numbers",
    })
    _lock_file = _PROJECT_ROOT / "_gate_bridge_active.lock"
    _is_ui_action = action in _UI_MUTATING_ACTIONS
    if _is_ui_action:
        try:
            _lock_file.touch()
        except Exception:
            pass

    exit_code = 0
    output = ""
    try:
        result = _call(action, payload)
        output = json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=_json_default)
    except Exception as exc:
        output = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        exit_code = 1
    finally:
        if _is_ui_action:
            try:
                _lock_file.unlink(missing_ok=True)
            except Exception:
                pass

    print(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
