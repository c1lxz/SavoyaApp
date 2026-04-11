from __future__ import annotations

from types import SimpleNamespace

from backend.app.scripts import gate_runtime


class _FakeCursor:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple | None]] = []

    def execute(self, sql: str, params=None):
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self


class _RowCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql: str, params=None):
        return self

    def fetchall(self):
        return list(self._rows)


class _InsertedUserCursor:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchval(self):
        if self._last_sql == "SELECT @@IDENTITY":
            return 0
        raise AssertionError(f"Unexpected fetchval() for SQL: {self._last_sql}")

    def fetchone(self):
        if "WHERE NumberU = ?" in self._last_sql:
            return SimpleNamespace(UserPtr=55)
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")


def test_build_identity_for_phone_populates_required_number(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_generate_unique_number_u", lambda cursor: "ABC123NUMBER")

    identity = gate_runtime._build_identity(object(), "Phone", "79991234567")

    assert identity.number == "79991234567"
    assert identity.phone == "79991234567"
    assert identity.number_u == "ABC123NUMBER"


def test_upsert_existing_phone_user_heals_number_field(monkeypatch):
    cursor = _FakeCursor()

    monkeypatch.setattr(gate_runtime, "_find_existing_user_ptr", lambda *args, **kwargs: 42)
    monkeypatch.setattr(gate_runtime, "_find_reusable_deleted_user_ptr", lambda *args, **kwargs: None)
    monkeypatch.setattr(gate_runtime, "_ensure_access_permissions", lambda *args, **kwargs: None)

    user_ptr = gate_runtime._upsert_real_user(
        cursor,
        key_type="Phone",
        normalized_key_value="79991234567",
        phone_number=None,
        resident_name="79991234567",
        is_visitor=True,
        expires_at=None,
        access_point_ids=[15],
    )

    assert user_ptr == 42
    assert any(
        sql == "UPDATE Users SET Phone = ?, [Number] = ? WHERE UserPtr = ?"
        and params == ("79991234567", "79991234567", 42)
        for sql, params in cursor.commands
    )
    assert any(
        sql == "UPDATE Users SET [LastName] = ? WHERE UserPtr = ?"
        and params == ("79991234567", 42)
        for sql, params in cursor.commands
    )


def test_normalize_phone_keeps_legacy_formats_compatible():
    assert gate_runtime._normalize_phone("8 (999) 123-45-67") == "79991234567"
    assert gate_runtime._normalize_phone("+7 999 123-45-67") == "79991234567"
    assert gate_runtime._normalize_phone("0079991234567") == "79991234567"


def test_find_existing_user_ptr_skips_zero_user_ptr():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=0, Phone="0079991234567", Number="0079991234567", Deleted=False),
            SimpleNamespace(UserPtr=17, Phone="79991234567", Number="79991234567", Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "79991234567")

    assert user_ptr == 17


def test_find_existing_user_ptr_matches_legacy_007_phone_value():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=18, Phone="0079991234567", Number="0079991234567", Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "79991234567")

    assert user_ptr == 18


def test_resolve_inserted_user_ptr_falls_back_when_identity_is_zero():
    cursor = _InsertedUserCursor()

    user_ptr = gate_runtime._resolve_inserted_user_ptr(cursor, number_u="ABC123NUMBER")

    assert user_ptr == 55
    assert cursor.commands == [
        ("SELECT @@IDENTITY", None),
        (
            """
        SELECT TOP 1 UserPtr
        FROM Users
        WHERE NumberU = ?
        ORDER BY UserPtr DESC
        """,
            ("ABC123NUMBER",),
        ),
    ]
