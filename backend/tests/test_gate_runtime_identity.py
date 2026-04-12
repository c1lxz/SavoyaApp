from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
    def __init__(self, rows_by_id) -> None:
        self._rows_by_id = rows_by_id
        self._last_sql = ""
        self._params = None

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self._params = tuple(params) if params is not None else None
        return self

    def fetchone(self):
        if "FROM Readers AS r" in self._last_sql:
            point_id = int(self._params[0])
            return self._rows_by_id.get(point_id)
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")


class _AccessPermissionCursor:
    def __init__(
        self,
        existing: bool,
        *,
        existing_inner_num: int | None = None,
        max_inner_num: int = 0,
        conflicting_inner_nums=None,
    ) -> None:
        self.existing = existing
        self.existing_inner_num = existing_inner_num
        self.max_inner_num = max_inner_num
        self.conflicting_inner_nums = set(conflicting_inner_nums or [])
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""
        self._params = None

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self._params = tuple(params) if params is not None else None
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchone(self):
        if "SELECT TOP 1 UserPtr, InnerNum FROM AccessTable WHERE UserPtr = ? AND RdrPtr = ?" in self._last_sql:
            if not self.existing:
                return None
            return SimpleNamespace(UserPtr=42, InnerNum=self.existing_inner_num)
        if "SELECT TOP 1 UserPtr FROM AccessTable WHERE RdrPtr = ? AND InnerNum = ?" in self._last_sql:
            inner_num = int(self._params[1])
            if inner_num in self.conflicting_inner_nums:
                return SimpleNamespace(UserPtr=999)
            return None
        if "SELECT MAX(InnerNum) AS MaxInnerNum FROM AccessTable WHERE RdrPtr = ?" in self._last_sql:
            return SimpleNamespace(MaxInnerNum=self.max_inner_num)
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")


class _TemplateSamplingCursor:
    def __init__(self, access_rows=None, user_rows=None) -> None:
        self.access_rows = list(access_rows or [])
        self.user_rows = list(user_rows or [])
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        return self

    def fetchall(self):
        if "AccessTable AS a" in self._last_sql:
            return list(self.access_rows)
        if "SELECT TOP 100 UserPtr, Phone, Number, KeyType, Deleted" in self._last_sql:
            return list(self.user_rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")

    def fetchone(self):
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")


@contextmanager
def _fake_transaction_cursor(cursor):
    yield None, cursor


def test_build_identity_for_phone_populates_required_number(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_generate_unique_number_u", lambda cursor: "ABC123NUMBER")
    monkeypatch.delenv("GATE_PHONE_WRITE_FORMAT", raising=False)
    monkeypatch.delenv("GATE_PHONE_STORAGE_FORMAT", raising=False)

    identity = gate_runtime._build_identity(object(), "Phone", "009991234567")

    assert identity.number == "009991234567"
    assert identity.phone == "9991234567"
    assert identity.number_u == "009991234567"


def test_build_identity_for_phone_matches_sample_storage_format(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_generate_unique_number_u", lambda cursor: "ABC123NUMBER")
    monkeypatch.setenv("GATE_PHONE_WRITE_FORMAT", "sample")
    monkeypatch.delenv("GATE_PHONE_STORAGE_FORMAT", raising=False)
    cursor = _PhoneSampleCursor("+79991234567")

    identity = gate_runtime._build_identity(cursor, "Phone", "009991234567")

    assert identity.number == "009991234567"
    assert identity.phone == "+79991234567"
    assert identity.number_u == "009991234567"


def test_insert_real_user_uses_storage_phone_for_phone_keys(monkeypatch):
    cursor = _FakeCursor()

    monkeypatch.setattr(gate_runtime, "_sample_user_defaults", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        gate_runtime,
        "_build_identity",
        lambda *args, **kwargs: gate_runtime.RealGateIdentity(
            number="009991234567",
            phone="89991234567",
            number_u="009991234567",
            number_mifare=None,
        ),
    )
    monkeypatch.setattr(gate_runtime, "_resolve_inserted_user_ptr", lambda *args, **kwargs: 55)

    user_ptr = gate_runtime._insert_real_user(
        cursor,
        key_type_value=6,
        key_type="Phone",
        normalized_key_value="009991234567",
        phone_number="+79991234567",
        resident_name="Phone User",
        is_visitor=True,
        expires_at=None,
    )

    assert user_ptr == 55
    assert any(
        sql.startswith("INSERT INTO Users")
        and params.count("89991234567") == 1
        and params.count("009991234567") == 2
        for sql, params in cursor.commands
    )


def test_upsert_existing_phone_user_heals_number_field(monkeypatch):
    cursor = _FakeCursor()

    monkeypatch.setenv("GATE_PHONE_WRITE_FORMAT", "local_10")
    monkeypatch.delenv("GATE_PHONE_STORAGE_FORMAT", raising=False)
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
        sql == "UPDATE Users SET Phone = ?, [Number] = ?, [NumberU] = ? WHERE UserPtr = ?"
        and params == ("9991234567", "009991234567", "009991234567", 42)
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
        {
            15: SimpleNamespace(RdrPtr=15, Name="Entry Camera", DeviceKeyType=3),
            70: SimpleNamespace(RdrPtr=70, Name="Gate Terminal Entry", DeviceKeyType=9),
        }
    )

    key_type = gate_runtime._sample_key_type(cursor, "Phone", [15, 70])

    assert key_type == 9


def test_ensure_access_permissions_updates_existing_rows(monkeypatch):
    cursor = _AccessPermissionCursor(existing=True, existing_inner_num=77)
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
        "UPDATE AccessTable" in sql and params[0] == 77 and params[-2:] == (42, 70)
        for sql, params in cursor.commands
    )


def test_ensure_access_permissions_inserts_new_rows_with_unique_inner_num(monkeypatch):
    cursor = _AccessPermissionCursor(existing=False, max_inner_num=100)
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
        "INSERT INTO AccessTable" in sql and params[:3] == (70, 42, 101)
        for sql, params in cursor.commands
    )


def test_ensure_access_permissions_reassigns_conflicting_inner_num(monkeypatch):
    cursor = _AccessPermissionCursor(existing=True, existing_inner_num=77, max_inner_num=100, conflicting_inner_nums={77})
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
        "UPDATE AccessTable" in sql and params[0] == 101 and params[-2:] == (42, 70)
        for sql, params in cursor.commands
    )


def test_permission_template_for_reader_skips_vehicle_rows_with_contact_phone(monkeypatch):
    cursor = _TemplateSamplingCursor(
        access_rows=[
            SimpleNamespace(
                InnerNum=11,
                Always=True,
                Schedule1=False,
                Schedule2=False,
                Schedule3=False,
                Schedule4=False,
                Schedule5=False,
                Schedule6=False,
                Schedule7=False,
                RecordState=0,
                APB=False,
                Inside=False,
                CardType=3,
                CardCode="CAR",
                NoEntry=False,
                NoExit=False,
                Phone="89991234567",
                Number="A182DC178",
                KeyType=3,
                Deleted=False,
            ),
            SimpleNamespace(
                InnerNum=22,
                Always=True,
                Schedule1=False,
                Schedule2=False,
                Schedule3=False,
                Schedule4=False,
                Schedule5=False,
                Schedule6=False,
                Schedule7=False,
                RecordState=0,
                APB=False,
                Inside=False,
                CardType=9,
                CardCode="PHONE",
                NoEntry=False,
                NoExit=False,
                Phone="89991234567",
                Number="009991234567",
                KeyType=6,
                Deleted=False,
            ),
        ]
    )

    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *_args, **_kwargs: 6)

    template = gate_runtime._permission_template_for_reader(cursor, 70, key_type="Phone")

    assert template["InnerNum"] == 22
    assert template["CardType"] == 9
    assert template["CardCode"] == "PHONE"


def test_sample_phone_storage_value_skips_vehicle_rows_with_contact_phone():
    cursor = _TemplateSamplingCursor(
        access_rows=[
            SimpleNamespace(
                Phone="+79991234567",
                Number="A182DC178",
                KeyType=3,
                Deleted=False,
                Name="GSM Entry",
            ),
            SimpleNamespace(
                Phone="89991234567",
                Number="009991234567",
                KeyType=6,
                Deleted=False,
                Name="GSM Entry",
            ),
        ]
    )

    assert gate_runtime._sample_phone_storage_value(cursor) == "89991234567"


def test_add_temporary_phone_key_marks_gate_user_as_non_visitor(monkeypatch):
    observed: dict[str, object] = {}
    cursor = _FakeCursor()

    monkeypatch.setattr(gate_runtime, "_transaction_cursor", lambda: _fake_transaction_cursor(cursor))
    monkeypatch.setattr(
        gate_runtime,
        "_upsert_real_user",
        lambda *args, **kwargs: observed.update(kwargs) or 77,
    )

    key_id = gate_runtime.add_temporary_key(
        key_type="Phone",
        key_value="+79991234567",
        phone_number="+79991234567",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        access_point_ids=[5, 6],
        resident_name="Phone User",
    )

    assert key_id == 77
    assert observed["is_visitor"] is False
    assert observed["resident_name"] == "Phone User"


def test_find_existing_user_ptr_skips_zero_user_ptr():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=0, Phone="0079991234567", Number="0079991234567", KeyType=6, Deleted=False),
            SimpleNamespace(UserPtr=17, Phone="009991234567", Number="009991234567", KeyType=6, Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "009991234567", key_type_value=6)

    assert user_ptr == 17


def test_find_existing_user_ptr_matches_legacy_007_phone_value():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=18, Phone="0079991234567", Number="0079991234567", KeyType=6, Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "009991234567", key_type_value=6)

    assert user_ptr == 18


def test_find_existing_user_ptr_matches_vehicle_number_with_mixed_alphabet():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=24, Phone=None, Number="А123АА77", Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "VehicleNumber", gate_runtime._normalize_vehicle("A123AA77"))

    assert user_ptr == 24


def test_find_existing_phone_user_ptr_ignores_vehicle_user_with_same_contact_phone():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=30, Phone="89111253128", Number="A182DC178", KeyType=3, Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "009111253128", key_type_value=6)

    assert user_ptr is None


def test_find_existing_phone_user_ptr_prefers_phone_row_when_vehicle_row_has_same_phone():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=31, Phone="89111253128", Number="A182DC178", KeyType=3, Deleted=False),
            SimpleNamespace(UserPtr=32, Phone="89111253128", Number="009111253128", KeyType=6, Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "009111253128", key_type_value=6)

    assert user_ptr == 32


def test_find_existing_phone_user_ptr_reuses_numeric_phone_row_even_if_key_type_is_stale():
    cursor = _RowCursor(
        [
            SimpleNamespace(UserPtr=33, Phone="89111253128", Number="89111253128", KeyType=3, Deleted=False),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "009111253128", key_type_value=6)

    assert user_ptr == 33


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
