from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os

import pytest

from backend.app.services import gate


@pytest.mark.parametrize(
    ("real_integration_enabled", "key_type", "expected_actions"),
    [
        # VehicleNumber keys are provisioned entirely inside add_permanent_key's bridge
        # action (via GateTerm UI in gate_runtime.py); there is no separate post-sync step.
        (True, "VehicleNumber", ["add_permanent_key"]),
        (True, "Phone", ["add_permanent_key", "post_sync_phone_key"]),
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
        if action in {"post_sync_vehicle_key", "post_sync_phone_key"}:
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


def test_add_permanent_key_does_not_call_post_sync_for_vehicle_keys(monkeypatch) -> None:
    """VehicleNumber keys must not trigger any separate post-sync action — provisioning
    happens fully inside the add_permanent_key bridge action via GateTerm UI."""
    client = gate.GateClient()
    actions: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", True)

    def _fake_run_bridge(action: str, payload=None):
        actions.append(action)
        if action == "add_permanent_key":
            return 321
        raise AssertionError(f"unexpected bridge action for vehicle key: {action}")

    monkeypatch.setattr(client, "_run_bridge", _fake_run_bridge)

    result = client.add_permanent_key(
        key_type="VehicleNumber",
        key_value="A123AA77",
        phone_number="+79991234567",
        access_point_ids=[1],
        resident_name="Test User",
    )

    assert result == 321
    assert actions == ["add_permanent_key"]


def test_add_permanent_key_keeps_created_phone_key_when_post_sync_fails(monkeypatch) -> None:
    client = gate.GateClient()
    actions: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", True)

    def _fake_run_bridge(action: str, payload=None):
        actions.append(action)
        if action == "add_permanent_key":
            return 321
        if action == "post_sync_phone_key":
            raise RuntimeError("post-sync failed")
        raise AssertionError(action)

    monkeypatch.setattr(client, "_run_bridge", _fake_run_bridge)

    result = client.add_permanent_key(
        key_type="Phone",
        key_value="+79991234567",
        phone_number="+79991234567",
        access_point_ids=[1],
        resident_name="Test User",
    )

    assert result == 321
    assert actions == ["add_permanent_key", "post_sync_phone_key"]


def test_add_account_phone_key_routes_through_dispatcher_ui_bridge(monkeypatch) -> None:
    client = gate.GateClient()
    actions: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", True)

    def _fake_run_bridge(action: str, payload=None):
        actions.append(action)
        return 654

    monkeypatch.setattr(client, "_run_bridge", _fake_run_bridge)

    result = client.add_account_phone_key(
        key_value="+79991234567",
        phone_number="+79991234567",
        access_point_ids=[15, 17, 19, 20, 21, 23, 5, 6],
        resident_name="Dispatcher Resident",
        plot_number="12",
    )

    assert result == 654
    assert actions == ["add_phone_permanent_key_via_ui"]


def test_resolve_key_id_routes_through_bridge(monkeypatch) -> None:
    client = gate.GateClient()
    actions: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", True)

    def _fake_run_bridge(action: str, payload=None):
        actions.append(action)
        assert payload == {"external_key_id": "+79991234567"}
        return 987

    monkeypatch.setattr(client, "_run_bridge", _fake_run_bridge)

    result = client.resolve_key_id("+79991234567")

    assert result == 987
    assert actions == ["resolve_key_id"]


def test_list_keys_by_phone_routes_through_bridge(monkeypatch) -> None:
    client = gate.GateClient()
    actions: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", True)

    def _fake_run_bridge(action: str, payload=None):
        actions.append(action)
        assert payload == {"phone_number": "+79991234567"}
        return [{"gate_key_id": 987, "key_type": "Phone", "key_value": "009991234567"}]

    monkeypatch.setattr(client, "_run_bridge", _fake_run_bridge)

    result = client.list_keys_by_phone("+79991234567")

    assert result == [{"gate_key_id": 987, "key_type": "Phone", "key_value": "009991234567"}]
    assert actions == ["list_keys_by_phone"]


def test_run_bridge_retries_transient_access_lock(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[object] = []

    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 2)
    monkeypatch.setattr(gate.settings, "gate_bridge_retry_delay_seconds", 0.0)
    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")
    monkeypatch.setattr(gate.time, "sleep", lambda *_args, **_kwargs: None)

    outcomes = [
        SimpleNamespace(
            returncode=1,
            stdout='{"ok": false, "error": "(\'HY000\', \'... (-1102) ...\')"}',
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout='{"ok": true, "result": 321}', stderr=""),
    ]

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return outcomes.pop(0)

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)

    result = client._run_bridge("add_temporary_key", {"key_type": "Phone"})

    assert result == 321
    assert len(calls) == 2


def test_run_bridge_retries_invalid_bookmark(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[object] = []

    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 2)
    monkeypatch.setattr(gate.settings, "gate_bridge_retry_delay_seconds", 0.0)
    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")
    monkeypatch.setattr(gate.time, "sleep", lambda *_args, **_kwargs: None)

    outcomes = [
        SimpleNamespace(
            returncode=1,
            stdout='{"ok": false, "error": "(\'HY000\', \'Недопустимая закладка. (-1045)\')"}',
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout='{"ok": true, "result": 654}', stderr=""),
    ]

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return outcomes.pop(0)

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)

    result = client._run_bridge("add_temporary_key", {"key_type": "VehicleNumber"})

    assert result == 654
    assert len(calls) == 2


def test_run_bridge_retries_transient_mdb_snapshot_failure(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[object] = []

    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 2)
    monkeypatch.setattr(gate.settings, "gate_bridge_retry_delay_seconds", 0.0)
    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")
    monkeypatch.setattr(gate.time, "sleep", lambda *_args, **_kwargs: None)

    outcomes = [
        SimpleNamespace(
            returncode=1,
            stdout='{"ok": false, "error": "Failed to connect to Gate MDB with available ODBC drivers: ... (-1206) ..."}',
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout='{"ok": true, "result": [{"id": 1, "name": "Entry"}]}', stderr=""),
    ]

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return outcomes.pop(0)

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)

    result = client._run_bridge("get_access_points")

    assert result == [{"id": 1, "name": "Entry"}]
    assert len(calls) == 2


def test_run_bridge_does_not_retry_non_retryable_error(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[object] = []

    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 3)
    monkeypatch.setattr(gate.settings, "gate_bridge_retry_delay_seconds", 0.0)
    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")
    monkeypatch.setattr(gate.time, "sleep", lambda *_args, **_kwargs: None)

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stdout="", stderr="plain fatal error")

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="plain fatal error"):
        client._run_bridge("add_temporary_key", {"key_type": "Phone"})

    assert len(calls) == 1


def test_run_bridge_uses_maintenance_timeout_for_repair_actions(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[object] = []

    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 1)
    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_bridge_maintenance_timeout_seconds", 300)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok": true, "result": {"updated": 0}}', stderr="")

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)

    result = client._run_bridge("repair_phone_identity_rows")

    assert result == {"updated": 0}
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 300


def test_run_bridge_retries_maintenance_actions_until_timeout_window(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[object] = []
    monotonic_values = iter([0.0, 0.0, 1.0, 1.0, 2.0, 2.0])

    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 1)
    monkeypatch.setattr(gate.settings, "gate_bridge_retry_delay_seconds", 0.0)
    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_bridge_maintenance_timeout_seconds", 300)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")
    monkeypatch.setattr(gate.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(monotonic_values))

    outcomes = [
        SimpleNamespace(
            returncode=1,
            stdout='{"ok": false, "error": "(\'HY000\', \'... (-1102) ...\')"}',
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout='{"ok": true, "result": {"updated": 3}}', stderr=""),
    ]

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return outcomes.pop(0)

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)

    result = client._run_bridge("repair_phone_identity_rows")

    assert result == {"updated": 3}
    assert len(calls) == 2


def test_run_bridge_serializes_mutating_actions_with_lock(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[object] = []
    lock_events: list[str] = []

    class _FakeLock:
        def __enter__(self):
            lock_events.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            lock_events.append("exit")
            return False

    monkeypatch.setattr(client, "_mutating_bridge_lock", _FakeLock())
    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 1)
    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok": true, "result": 321}', stderr="")

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)

    result = client._run_bridge("add_permanent_key", {"key_type": "Phone"})

    assert result == 321
    assert len(calls) == 1
    assert lock_events == ["enter", "exit"]


def test_run_bridge_passes_utf8_payload_over_stdin(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 1)
    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok": true, "result": 321}', stderr="")

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)

    result = client._run_bridge(
        "add_temporary_key",
        {
            "key_type": "Phone",
            "resident_name": "Бридж Тест Телефон",
            "phone_number": "+79991234567",
        },
    )

    assert result == 321
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (["py", "-3.12-32", str(gate._GATE_BRIDGE_SCRIPT), "add_temporary_key"],)
    assert kwargs["input"] == (
        '{"key_type": "Phone", "resident_name": "Бридж Тест Телефон", "phone_number": "+79991234567"}'
    )
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert kwargs["env"]["PYTHONUTF8"] == "1"


def test_run_bridge_uses_vehicle_post_sync_timeout(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 1)
    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_bridge_vehicle_post_sync_timeout_seconds", 60)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok": true, "result": {"user_ptr": 321}}', stderr="")

    monkeypatch.setattr(gate.subprocess, "run", _fake_run)

    result = client._run_bridge("post_sync_vehicle_key", {"key_id": 321})

    assert result == {"user_ptr": 321}
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 60


def test_ensure_gateterm_users_guard_running_starts_sidecar(monkeypatch) -> None:
    client = gate.GateClient()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    fake_process = SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", True)
    monkeypatch.setattr(gate.settings, "gate_gateterm_users_guard_enabled", True)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")
    monkeypatch.setattr(gate, "_GATETERM_USERS_GUARD_SCRIPT", Path("scripts/gateterm_users_guard.py"))

    def _fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return fake_process

    monkeypatch.setattr(gate.subprocess, "Popen", _fake_popen)

    client.ensure_gateterm_users_guard_running()

    assert client._gateterm_users_guard_process is fake_process
    assert calls == [
        (
            (["py", "-3.12-32", "scripts\\gateterm_users_guard.py", "--parent-pid", str(os.getpid())],),
            {
                "cwd": gate._PROJECT_ROOT,
                "stdin": gate.subprocess.DEVNULL,
                "env": {
                    **os.environ,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                },
                "creationflags": int(getattr(gate.subprocess, "CREATE_NO_WINDOW", 0) or 0),
            },
        )
    ]


def test_ensure_gateterm_users_guard_running_skips_when_disabled(monkeypatch) -> None:
    client = gate.GateClient()

    monkeypatch.setattr(gate.settings, "gate_real_integration_enabled", True)
    monkeypatch.setattr(gate.settings, "gate_gateterm_users_guard_enabled", False)
    monkeypatch.setattr(
        gate.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Popen should not be called")),
    )

    client.ensure_gateterm_users_guard_running()

    assert client._gateterm_users_guard_process is None


def test_stop_gateterm_users_guard_terminates_live_process() -> None:
    client = gate.GateClient()
    calls: list[tuple[str, object | None]] = []

    class _FakeProcess:
        def poll(self):
            calls.append(("poll", None))
            return None

        def terminate(self):
            calls.append(("terminate", None))

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return 0

    client._gateterm_users_guard_process = _FakeProcess()

    client.stop_gateterm_users_guard()

    assert client._gateterm_users_guard_process is None
    assert calls == [("poll", None), ("terminate", None), ("wait", 5)]


def test_run_bridge_ensures_gateterm_users_guard_for_guarded_action(monkeypatch) -> None:
    client = gate.GateClient()
    ensured: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 1)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")
    monkeypatch.setattr(client, "ensure_gateterm_users_guard_running", lambda: ensured.append("guard"))
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='{"ok": true, "result": {"user_ptr": 9}}', stderr=""),
    )

    result = client._run_bridge("repair_vehicle_visual_numbers", {"limit": 9})

    assert result == {"user_ptr": 9}
    assert ensured == ["guard"]


def test_run_bridge_skips_gateterm_users_guard_for_vehicle_post_sync(monkeypatch) -> None:
    client = gate.GateClient()
    ensured: list[str] = []

    monkeypatch.setattr(gate.settings, "gate_bridge_timeout_seconds", 20)
    monkeypatch.setattr(gate.settings, "gate_bridge_vehicle_post_sync_timeout_seconds", 60)
    monkeypatch.setattr(gate.settings, "gate_bridge_retry_attempts", 1)
    monkeypatch.setattr(gate.settings, "gate_python_launcher", "py")
    monkeypatch.setattr(gate.settings, "gate_python_version", "-3.12-32")
    monkeypatch.setattr(client, "ensure_gateterm_users_guard_running", lambda: ensured.append("guard"))
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='{"ok": true, "result": {"user_ptr": 9}}', stderr=""),
    )

    result = client._run_bridge("post_sync_vehicle_key", {"key_id": 9})

    assert result == {"user_ptr": 9}
    assert ensured == []
