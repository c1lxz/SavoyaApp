from __future__ import annotations

from backend.app.scripts import gate_runtime


class _FakeCursor:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple | None]] = []

    def execute(self, sql: str, params=None):
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self


def test_build_identity_for_phone_populates_required_number(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_generate_unique_number_u", lambda cursor: "ABC123NUMBER")

    identity = gate_runtime._build_identity(object(), "Phone", "0079991234567")

    assert identity.number == "0079991234567"
    assert identity.phone == "0079991234567"
    assert identity.number_u == "ABC123NUMBER"


def test_upsert_existing_phone_user_heals_number_field(monkeypatch):
    cursor = _FakeCursor()

    monkeypatch.setattr(gate_runtime, "_find_existing_user_ptr", lambda *args, **kwargs: 42)
    monkeypatch.setattr(gate_runtime, "_find_reusable_deleted_user_ptr", lambda *args, **kwargs: None)
    monkeypatch.setattr(gate_runtime, "_ensure_access_permissions", lambda *args, **kwargs: None)

    user_ptr = gate_runtime._upsert_real_user(
        cursor,
        key_type="Phone",
        normalized_key_value="0079991234567",
        phone_number=None,
        resident_name="Иванов Иван",
        is_visitor=True,
        expires_at=None,
        access_point_ids=[15],
    )

    assert user_ptr == 42
    assert any(
        sql == "UPDATE Users SET Phone = ?, [Number] = ? WHERE UserPtr = ?"
        and params == ("0079991234567", "0079991234567", 42)
        for sql, params in cursor.commands
    )
