from __future__ import annotations

from datetime import datetime, timezone

import gate_db


class _StubRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def add_permanent_key(self, *args):
        self.calls.append(("add_permanent_key", args))
        return 101

    def add_temporary_key(self, *args):
        self.calls.append(("add_temporary_key", args))
        return 202


def test_add_permanent_key_forwards_phone_number_and_resident_name(monkeypatch):
    runtime = _StubRuntime()
    monkeypatch.setattr(gate_db, "_runtime", lambda: runtime)

    result = gate_db.add_permanent_key(
        key_type="Phone",
        key_value="+79991234567",
        access_point_ids=[5, 6],
        phone_number="+79991234567",
        resident_name="Test User",
    )

    assert result == 101
    assert runtime.calls == [
        (
            "add_permanent_key",
            ("Phone", "+79991234567", "+79991234567", [5, 6], "Test User"),
        )
    ]


def test_add_temporary_key_forwards_phone_number_expiry_and_resident_name(monkeypatch):
    runtime = _StubRuntime()
    monkeypatch.setattr(gate_db, "_runtime", lambda: runtime)
    expires_at = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)

    result = gate_db.add_temporary_key(
        key_type="Phone",
        key_value="+79991234567",
        expires_at=expires_at,
        access_point_ids=[5, 6],
        phone_number="+79991234567",
        resident_name="Test User",
    )

    assert result == 202
    assert runtime.calls == [
        (
            "add_temporary_key",
            ("Phone", "+79991234567", "+79991234567", expires_at, [5, 6], "Test User"),
        )
    ]
