from __future__ import annotations

from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_guard_module():
    project_root = Path(__file__).resolve().parents[2]
    spec = spec_from_file_location("gateterm_users_guard", project_root / "scripts" / "gateterm_users_guard.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load gateterm_users_guard.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_safe_anchor_key_prefers_explicit_env(monkeypatch) -> None:
    guard = _load_guard_module()

    monkeypatch.setattr(
        guard.gate_runtime,
        "_env",
        lambda name, *aliases, default=None, allow_empty=False: (
            "A777AA77" if name == "GATE_GATETERM_USERS_GUARD_ANCHOR_KEY" else default
        ),
    )
    monkeypatch.setattr(
        guard.gate_runtime,
        "_readonly_cursor",
        lambda: (_ for _ in ()).throw(AssertionError("_readonly_cursor should not be called")),
    )

    assert guard._resolve_safe_anchor_key() == "A777AA77"


def test_configured_anchor_key_types_parses_csv(monkeypatch) -> None:
    guard = _load_guard_module()

    monkeypatch.setattr(
        guard.gate_runtime,
        "_env",
        lambda name, *aliases, default=None, allow_empty=False: "3, 8 ; 11" if name == "GATE_GATETERM_USERS_GUARD_ANCHOR_KEY_TYPES" else default,
    )

    assert guard._configured_anchor_key_types() == [3, 8, 11]


def test_configured_anchor_key_types_rejects_invalid_values(monkeypatch) -> None:
    guard = _load_guard_module()

    monkeypatch.setattr(
        guard.gate_runtime,
        "_env",
        lambda name, *aliases, default=None, allow_empty=False: "3, nope" if name == "GATE_GATETERM_USERS_GUARD_ANCHOR_KEY_TYPES" else default,
    )

    with pytest.raises(RuntimeError, match="Invalid GATE_GATETERM_USERS_GUARD_ANCHOR_KEY_TYPES"):
        guard._configured_anchor_key_types()


def test_excluded_anchor_keys_parses_csv(monkeypatch) -> None:
    guard = _load_guard_module()

    monkeypatch.setattr(
        guard.gate_runtime,
        "_env",
        lambda name, *aliases, default=None, allow_empty=False: "078B424DEEFF, abc123 ; qwe987" if name == "GATE_GATETERM_USERS_GUARD_EXCLUDED_KEYS" else default,
    )

    assert guard._excluded_anchor_keys() == {
        "078b424deeff",
        "abc123",
        "qwe987",
    }


def test_parent_pid_is_alive_uses_os_kill_on_non_windows(monkeypatch) -> None:
    guard = _load_guard_module()
    observed: list[tuple[int, int]] = []

    def _fake_kill(pid: int, signal: int) -> None:
        observed.append((pid, signal))

    monkeypatch.setattr(guard.os, "name", "posix", raising=False)
    monkeypatch.setattr(guard.os, "kill", _fake_kill)

    assert guard._parent_pid_is_alive(3210) is True
    assert observed == [(3210, 0)]


def test_parent_pid_is_alive_uses_windows_process_handle(monkeypatch) -> None:
    guard = _load_guard_module()
    calls: list[tuple[str, int]] = []

    class _FakeKernel32:
        def OpenProcess(self, desired_access, inherit_handle, pid):
            calls.append(("open", int(pid)))
            return 123

        def GetExitCodeProcess(self, handle, exit_code_pointer):
            calls.append(("exit_code", int(handle)))
            exit_code_pointer._obj.value = 259
            return 1

        def CloseHandle(self, handle):
            calls.append(("close", int(handle)))
            return 1

    monkeypatch.setattr(guard.os, "name", "nt", raising=False)
    monkeypatch.setattr(guard.ctypes, "windll", SimpleNamespace(kernel32=_FakeKernel32()))

    assert guard._parent_pid_is_alive(4321) is True
    assert calls == [("open", 4321), ("exit_code", 123), ("close", 123)]


def test_main_exits_when_parent_pid_is_gone(monkeypatch) -> None:
    guard = _load_guard_module()
    messages: list[str] = []

    monkeypatch.setattr(guard, "_parent_pid_is_alive", lambda parent_pid: False)
    monkeypatch.setattr(guard, "_log", lambda message: messages.append(message))
    monkeypatch.setattr(guard.gate_runtime, "_env", lambda name, *aliases, default=None, allow_empty=False: default)

    result = guard.main(["--parent-pid", "4321"])

    assert result == 0
    assert messages == [
        "GateTerm users guard started (parent_pid=4321)",
        "GateTerm users guard: parent pid 4321 is gone, exiting",
    ]


def test_interrupted_vb6_recordset_dialog_matches_error_91_text() -> None:
    guard = _load_guard_module()
    dialog = SimpleNamespace(
        window_text=lambda: "GateTerm",
        texts=lambda: ["GateTerm", "Object variable or With block variable not set", "OK"],
    )

    assert guard._is_interrupted_vb6_recordset_dialog(dialog) is True


def test_interrupted_vb6_recordset_dialog_ignores_other_confirmations() -> None:
    guard = _load_guard_module()
    dialog = SimpleNamespace(
        window_text=lambda: "GateTerm",
        texts=lambda: ["GateTerm", "Continue saving changes?", "Yes", "No"],
    )

    assert guard._is_interrupted_vb6_recordset_dialog(dialog) is False


def test_resolve_safe_anchor_key_scans_configured_key_types(monkeypatch) -> None:
    guard = _load_guard_module()
    queries: list[tuple[str, tuple[int]]] = []

    class _FakeCursor:
        def execute(self, sql: str, params=None):
            queries.append((sql, tuple(params)))
            return self

        def fetchone(self):
            key_type = queries[-1][1][0]
            if key_type == 8:
                return SimpleNamespace(Number="WG-ANCHOR-8")
            return None

    @contextmanager
    def _fake_readonly_cursor():
        yield None, _FakeCursor()

    monkeypatch.setattr(
        guard.gate_runtime,
        "_env",
        lambda name, *aliases, default=None, allow_empty=False: (
            "" if name == "GATE_GATETERM_USERS_GUARD_ANCHOR_KEY" else ("3,8,11" if name == "GATE_GATETERM_USERS_GUARD_ANCHOR_KEY_TYPES" else default)
        ),
    )
    monkeypatch.setattr(guard.gate_runtime, "_readonly_cursor", _fake_readonly_cursor)

    assert guard._resolve_safe_anchor_key() == "WG-ANCHOR-8"
    assert [params[0] for _sql, params in queries] == [3, 8]


def test_resolve_safe_anchor_key_skips_excluded_values(monkeypatch) -> None:
    guard = _load_guard_module()
    calls: list[int] = []

    class _FakeCursor:
        def execute(self, sql: str, params=None):
            calls.append(int(params[0]))
            return self

        def fetchone(self):
            key_type = calls[-1]
            if key_type == 3:
                return SimpleNamespace(Number="078B424DEEFF")
            if key_type == 6:
                return SimpleNamespace(Number="SAFE-KEY-6")
            return None

    @contextmanager
    def _fake_readonly_cursor():
        yield None, _FakeCursor()

    monkeypatch.setattr(
        guard.gate_runtime,
        "_env",
        lambda name, *aliases, default=None, allow_empty=False: (
            ""
            if name == "GATE_GATETERM_USERS_GUARD_ANCHOR_KEY"
            else ("3,6" if name == "GATE_GATETERM_USERS_GUARD_ANCHOR_KEY_TYPES" else ("078B424DEEFF" if name == "GATE_GATETERM_USERS_GUARD_EXCLUDED_KEYS" else default))
        ),
    )
    monkeypatch.setattr(guard.gate_runtime, "_readonly_cursor", _fake_readonly_cursor)

    assert guard._resolve_safe_anchor_key() == "SAFE-KEY-6"
    assert calls == [3, 6]
