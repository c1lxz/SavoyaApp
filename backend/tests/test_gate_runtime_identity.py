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


class _PhoneSampleCursor:
    def __init__(self, sample_phone: str) -> None:
        self.sample_phone = sample_phone
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        return self

    def fetchone(self):
        if "SELECT TOP 1 Phone" in self._last_sql:
            return SimpleNamespace(Phone=self.sample_phone)
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")


class _ReaderKeyTypeCursor:
    def __init__(self, rows) -> None:
        self._rows = rows
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        return self

    def fetchall(self):
        if "FROM Readers AS r" in self._last_sql:
            return list(self._rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")


class _AccessPermissionCursor:
    def __init__(self, existing: bool) -> None:
        self.existing = existing
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchone(self):
        if "SELECT TOP 1 UserPtr FROM AccessTable WHERE UserPtr = ? AND RdrPtr = ?" in self._last_sql:
            return SimpleNamespace(UserPtr=42) if self.existing else None
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")


def test_build_identity_for_phone_populates_required_number(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_generate_unique_number_u", lambda cursor: "ABC123NUMBER")
    monkeypatch.delenv("GATE_PHONE_WRITE_FORMAT", raising=False)
    monkeypatch.delenv("GATE_PHONE_STORAGE_FORMAT", raising=False)

    identity = gate_runtime._build_identity(object(), "Phone", "009991234567")

    assert identity.number == "009991234567"
    assert identity.phone == "009991234567"
    assert identity.number_u == "ABC123NUMBER"


def test_build_identity_for_phone_matches_sample_storage_format(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_generate_unique_number_u", lambda cursor: "ABC123NUMBER")
    monkeypatch.delenv("GATE_PHONE_WRITE_FORMAT", raising=False)
    monkeypatch.delenv("GATE_PHONE_STORAGE_FORMAT", raising=False)
    cursor = _PhoneSampleCursor("+79991234567")

    identity = gate_runtime._build_identity(cursor, "Phone", "009991234567")

    assert identity.number == "+79991234567"
    assert identity.phone == "+79991234567"
    assert identity.number_u == "ABC123NUMBER"


def test_upsert_existing_phone_user_heals_number_field(monkeypatch):
    cursor = _FakeCursor()

    monkeypatch.setattr(gate_runtime, "_find_existing_user_ptr", lambda *args, **kwargs: 42)
    monkeypatch.setattr(gate_runtime, "_find_reusable_deleted_user_ptr", lambda *args, **kwargs: None)
    monkeypatch.setattr(gate_runtime, "_ensure_access_permissions", lambda *args, **kwargs: None)

    user_ptr = gate_runtime._upsert_real_user(
        cursor,
        key_type="Phone",
        normalized_key_value="009991234567",
        phone_number=None,
        resident_name="009991234567",
        is_visitor=True,
        expires_at=None,
        access_point_ids=[15],
    )

    assert user_ptr == 42
    assert any(
        sql == "UPDATE Users SET Phone = ?, [Number] = ? WHERE UserPtr = ?"
        and params == ("009991234567", "009991234567", 42)
        for sql, params in cursor.commands
    )
    assert any(
        sql == "UPDATE Users SET [LastName] = ? WHERE UserPtr = ?"
        and params == ("009991234567", 42)
        for sql, params in cursor.commands
    )


def test_normalize_phone_keeps_legacy_formats_compatible():
    assert gate_runtime._normalize_phone("8 (999) 123-45-67") == "009991234567"
    assert gate_runtime._normalize_phone("+7 999 123-45-67") == "009991234567"
    assert gate_runtime._normalize_phone("0079991234567") == "009991234567"
    assert gate_runtime._normalize_phone("9991234567") == "009991234567"


def test_normalize_vehicle_canonicalizes_lookalikes_and_separators():
    assert gate_runtime._normalize_vehicle("A 123-AA 77") == "А123АА77"


def test_sample_key_type_prefers_phone_reader_device_key_type(monkeypatch):
    monkeypatch.delenv("GATE_REAL_KEYTYPE_PHONE", raising=False)
    cursor = _ReaderKeyTypeCursor(
        [
            SimpleNamespace(RdrPtr=15, Name="Entry Camera", KeyType=3),
            SimpleNamespace(RdrPtr=70, Name="Gate Terminal Entry", KeyType=9),
        ]
    )

    key_type = gate_runtime._sample_key_type(cursor, "Phone", [15, 70])

    assert key_type == 9


def test_ensure_access_permissions_updates_existing_rows(monkeypatch):
    cursor = _AccessPermissionCursor(existing=True)
    template = {
        "InnerNum": 1,
        "Always": True,
        "Schedule1": False,
        "Schedule2": False,
        "Schedule3": False,
        "Schedule4": False,
        "Schedule5": False,
        "Schedule6": False,
        "Schedule7": False,
        "RecordState": 0,
        "APB": False,
        "Inside": False,
        "CardType": 9,
        "CardCode": "PHONE",
        "NoEntry": False,
        "NoExit": False,
    }

    monkeypatch.setattr(gate_runtime, "_reader_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(gate_runtime, "_permission_template_for_reader", lambda *_args, **_kwargs: template)

    gate_runtime._ensure_access_permissions(cursor, 42, [70], key_type="Phone")

    assert any(
        "UPDATE AccessTable" in sql and params[-2:] == (42, 70)
        for sql, params in cursor.commands
    )


def test_find_existing_user_ptr_skips_zero_user_ptr():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=0, Phone="0079991234567", Number="0079991234567", Deleted=False),
            SimpleNamespace(UserPtr=17, Phone="009991234567", Number="009991234567", Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "009991234567")

    assert user_ptr == 17


def test_find_existing_user_ptr_matches_legacy_007_phone_value():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=18, Phone="0079991234567", Number="0079991234567", Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "009991234567")

    assert user_ptr == 18


def test_find_existing_user_ptr_matches_vehicle_number_with_mixed_alphabet():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=24, Phone=None, Number="А123АА77", Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "VehicleNumber", gate_runtime._normalize_vehicle("A123AA77"))

    assert user_ptr == 24


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
