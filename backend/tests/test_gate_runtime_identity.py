from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

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


class _ConflictCleanupCursor:
    def __init__(self, rows) -> None:
        self._rows = list(rows)
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchall(self):
        if "SELECT UserPtr, Phone, Number" in self._last_sql and "FROM Users" in self._last_sql:
            return list(self._rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")


class _AccessPruneCursor:
    def __init__(self, rows) -> None:
        self._rows = list(rows)
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchall(self):
        if "SELECT RdrPtr FROM AccessTable WHERE UserPtr = ?" in self._last_sql:
            return list(self._rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")


class _PhoneVerificationCursor:
    def __init__(self, user_row, access_rows) -> None:
        self.user_row = user_row
        self.access_rows = list(access_rows)
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        return self

    def fetchone(self):
        if "FROM Users" in self._last_sql and "WHERE UserPtr = ?" in self._last_sql:
            return self.user_row
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")

    def fetchall(self):
        if "FROM AccessTable" in self._last_sql and "WHERE UserPtr = ?" in self._last_sql:
            return list(self.access_rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")


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


class _UserActiveCursor:
    def __init__(self, row) -> None:
        self._row = row

    def execute(self, sql: str, params=None):
        return self

    def fetchone(self):
        return self._row


class _ResolveUserPtrCursor:
    def __init__(self, rows) -> None:
        self._rows = list(rows)
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchone(self):
        if "WHERE UserPtr = ?" in self._last_sql:
            return None
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")

    def fetchall(self):
        if "SELECT UserPtr, Phone, Number, NumberU, Deleted" in self._last_sql:
            return list(self._rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")


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
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchall(self):
        if "AccessTable AS a" in self._last_sql:
            return list(self.access_rows)
        if "SELECT TOP 100 UserPtr, Phone, Number, KeyType, Deleted" in self._last_sql:
            return list(self.user_rows)
        if "SELECT TOP 100" in self._last_sql and "GroupPtr" in self._last_sql and "FROM Users" in self._last_sql:
            return list(self.user_rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")

    def fetchone(self):
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")


class _VehicleRepairCursor:
    def __init__(self, rows) -> None:
        self._rows = list(rows)
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchall(self):
        if "SELECT UserPtr, KeyType, Number, NumberU, Deleted" in self._last_sql:
            return list(self._rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")


class _FakeMenuItem:
    def __init__(self, *, on_click=None, children=None) -> None:
        self._on_click = on_click
        self._children = list(children or [])

    def click(self):
        if self._on_click is not None:
            return self._on_click()
        return None

    def sub_menu(self):
        return self

    def items(self):
        return list(self._children)


class _FakeUsersWindow:
    def __init__(self, call_log) -> None:
        self.call_log = call_log
        search_item = _FakeMenuItem(on_click=lambda: self.call_log.append("search_menu_click"))
        edit_item = _FakeMenuItem(on_click=lambda: self.call_log.append("edit_menu_click"))
        self._menu_items = [
            _FakeMenuItem(children=[_FakeMenuItem(), edit_item]),
            _FakeMenuItem(),
            _FakeMenuItem(),
            _FakeMenuItem(),
            _FakeMenuItem(children=[search_item]),
        ]

    def set_focus(self):
        self.call_log.append("users_focus")

    def type_keys(self, value: str):
        self.call_log.append(("users_hotkey", value))

    def menu(self):
        return _FakeMenuItem(children=self._menu_items)


class _FakeGateUiWindow:
    def __init__(
        self,
        *,
        title: str,
        class_name: str,
        handle: int,
        menu_items=None,
        call_log=None,
        menu_select_error: Exception | None = None,
        enabled: bool = True,
    ) -> None:
        self._title = title
        self._class_name = class_name
        self.handle = handle
        self._menu_items = list(menu_items or [])
        self._call_log = call_log
        self._menu_select_error = menu_select_error
        self._enabled = enabled

    def window_text(self):
        return self._title

    def class_name(self):
        return self._class_name

    def menu(self):
        return _FakeMenuItem(children=self._menu_items) if self._menu_items else None

    def menu_select(self, path: str):
        if self._menu_select_error is not None:
            raise self._menu_select_error
        if self._call_log is not None:
            self._call_log.append(("menu_select", path))

    def set_focus(self):
        if self._call_log is not None:
            self._call_log.append(("focus", self.handle))

    def is_enabled(self):
        return self._enabled


class _FakeGateUiApp:
    def __init__(self, windows) -> None:
        self._windows = {window.handle: window for window in windows}

    def windows(self):
        return list(self._windows.values())

    def window(self, *, handle):
        return self._windows[handle]


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


def test_build_identity_for_vehicle_uses_vehicle_number_for_number_u(monkeypatch):
    monkeypatch.setenv("GATE_VEHICLE_NUMBER_U_MODE", "plate")
    identity = gate_runtime._build_identity(object(), "VehicleNumber", "A123AA77")

    assert identity.number == "A123AA77"
    assert identity.phone is None
    assert identity.number_u == "A123AA77"


def test_build_identity_for_vehicle_uses_random_number_u_in_random_mode(monkeypatch):
    monkeypatch.setenv("GATE_VEHICLE_NUMBER_U_MODE", "random")
    monkeypatch.setattr(gate_runtime, "_generate_unique_number_u", lambda cursor: "ABC123NUMBER")

    identity = gate_runtime._build_identity(object(), "VehicleNumber", "A123AA77")

    assert identity.number_u == "ABC123NUMBER"


def test_insert_real_vehicle_user_stores_vehicle_number_in_number_u(monkeypatch):
    cursor = _FakeCursor()

    monkeypatch.setenv("GATE_VEHICLE_NUMBER_U_MODE", "plate")
    monkeypatch.setattr(gate_runtime, "_sample_user_defaults", lambda *args, **kwargs: {})
    monkeypatch.setattr(gate_runtime, "_resolve_inserted_user_ptr", lambda *args, **kwargs: 55)

    user_ptr = gate_runtime._insert_real_user(
        cursor,
        key_type_value=3,
        key_type="VehicleNumber",
        normalized_key_value="A123AA77",
        phone_number="+79991234567",
        resident_name="Vehicle User",
        plot_number=None,
        is_visitor=False,
        expires_at=None,
    )

    assert user_ptr == 55
    assert any(
        sql.startswith("INSERT INTO Users")
        and params.count("A123AA77") >= 2
        for sql, params in cursor.commands
    )


def test_window_contains_vehicle_key_rejects_empty_or_wrong_values():
    assert gate_runtime._window_contains_vehicle_key([], "A123AA77") is False
    assert gate_runtime._window_contains_vehicle_key(["Изменение пользователя", ""], "A123AA77") is False
    assert gate_runtime._window_contains_vehicle_key(["Изменение пользователя", "A123AA77"], "A123AA77") is True


def test_open_gateterm_user_search_window_falls_back_to_hotkey(monkeypatch):
    call_log: list[object] = []
    users_window = _FakeUsersWindow(call_log)
    search_window = object()
    search_results = iter([None, search_window])

    monkeypatch.setattr(
        gate_runtime,
        "_try_wait_for_gateterm_window",
        lambda *args, **kwargs: next(search_results),
    )

    result = gate_runtime._open_gateterm_user_search_window(object(), users_window)

    assert result is search_window
    assert call_log == ["users_focus", "search_menu_click", "users_focus", ("users_hotkey", "^f")]


def test_find_gateterm_main_window_prefers_visible_form_with_menu():
    hidden_main = _FakeGateUiWindow(title="GateTerm", class_name="ThunderRT6Main", handle=1)
    visible_main = _FakeGateUiWindow(
        title="GATE Terminal.  Версия 1.22.99",
        class_name="ThunderRT6FormDC",
        handle=2,
        menu_items=[_FakeMenuItem()],
    )
    app = _FakeGateUiApp([hidden_main, visible_main])

    result = gate_runtime._find_gateterm_main_window(app)

    assert result is visible_main


def test_open_gateterm_users_view_falls_back_to_menu_click(monkeypatch):
    call_log: list[object] = []
    open_users_item = _FakeMenuItem(on_click=lambda: call_log.append("users_menu_click"))
    main_window = _FakeGateUiWindow(
        title="GATE Terminal.  Версия 1.22.99",
        class_name="ThunderRT6FormDC",
        handle=10,
        menu_items=[
            _FakeMenuItem(),
            _FakeMenuItem(children=[open_users_item]),
        ],
        call_log=call_log,
        menu_select_error=RuntimeError("There is no menu."),
    )
    users_window = _FakeGateUiWindow(
        title="Список пользователей",
        class_name="ThunderRT6FormDC",
        handle=11,
        call_log=call_log,
    )

    monkeypatch.setattr(gate_runtime, "_try_wait_for_gateterm_window", lambda *args, **kwargs: None)
    monkeypatch.setattr(gate_runtime, "_find_gateterm_main_window", lambda app: main_window)
    monkeypatch.setattr(gate_runtime, "_wait_for_enabled_gateterm_window", lambda *args, **kwargs: users_window)

    result = gate_runtime._open_gateterm_users_view(object())

    assert result is users_window
    assert call_log == [
        ("focus", 10),
        "users_menu_click",
        ("focus", 11),
    ]


def test_post_sync_vehicle_key_via_gateterm_ui_uses_clean_search_then_edit_flow(monkeypatch):
    calls: list[object] = []
    fake_app = object()
    fake_users_window = object()
    fake_edit_window = object()

    class _FakeApplication:
        def __init__(self, *args, **kwargs) -> None:
            calls.append(("application_init", kwargs))

        def connect(self, *, path):
            calls.append(("connect", path))
            return fake_app

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Application=_FakeApplication))
    monkeypatch.setattr(
        gate_runtime,
        "_env",
        lambda name, *aliases, default=None, allow_empty=False: (
            r"C:\GATE\Terminal\GateTerm.exe" if name == "GATE_GATETERM_EXE" else default
        ),
    )
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_close_gateterm_message_boxes_if_open", lambda app: calls.append("close_messages"))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_search_window_if_open", lambda app: calls.append("close_search"))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_user_edit_window_if_open", lambda app: calls.append("close_edit"))
    monkeypatch.setattr(gate_runtime, "_open_gateterm_users_view", lambda app: calls.append("open_users") or fake_users_window)
    monkeypatch.setattr(
        gate_runtime,
        "_search_gateterm_user_by_key_number",
        lambda app, users_window, normalized_key_value: calls.append(("search", users_window, normalized_key_value)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_open_gateterm_user_edit_window",
        lambda app, users_window: calls.append(("open_edit", users_window)) or fake_edit_window,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_collect_gateterm_window_values",
        lambda window: calls.append(("collect", window)) or ["A132FG777"],
    )
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda window, control_id, *class_names: calls.append(("click", window, control_id, class_names)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_verify_vehicle_identity_persisted",
        lambda user_ptr, normalized_key_value, expected_number_u: calls.append(
            ("verify", user_ptr, normalized_key_value, expected_number_u)
        ),
    )

    result = gate_runtime._post_sync_vehicle_key_via_gateterm_ui(
        user_ptr=42,
        normalized_key_value="A132FG777",
        expected_number_u="A132FG777",
    )

    assert result == {
        "transport": "gateterm_ui",
        "user_ptr": 42,
        "key_value": "A132FG777",
    }
    assert calls == [
        ("application_init", {"backend": "win32"}),
        ("connect", r"C:\GATE\Terminal\GateTerm.exe"),
        "close_messages",
        "close_search",
        "close_edit",
        "close_messages",
        "close_search",
        "open_users",
        ("search", fake_users_window, "A132FG777"),
        ("open_edit", fake_users_window),
        ("collect", fake_edit_window),
        ("click", fake_edit_window, 1, ("ThunderRT6CommandButton", "Button")),
        ("verify", 42, "A132FG777", "A132FG777"),
    ]


def test_split_access_expiry_separates_date_and_time():
    local_expiry = datetime(2026, 4, 13, 7, 43, 29, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    expiry_date, expiry_time = gate_runtime._split_access_expiry(
        datetime(2026, 4, 13, 7, 43, 29, tzinfo=timezone.utc),
        key_type="VehicleNumber",
    )

    assert expiry_date == datetime.combine(local_expiry.date(), time.min)
    assert expiry_time == datetime.combine(date(1899, 12, 30), local_expiry.time())


def test_split_access_expiry_for_phone_uses_date_only_format():
    local_expiry = datetime(2026, 4, 13, 7, 43, 29, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    expiry_date, expiry_time = gate_runtime._split_access_expiry(
        datetime(2026, 4, 13, 7, 43, 29, tzinfo=timezone.utc),
        key_type="Phone",
    )

    assert expiry_date == datetime.combine(local_expiry.date(), time.min)
    assert expiry_time == datetime(1899, 12, 30, 0, 0, 0)


def test_build_identity_for_phone_matches_sample_storage_format(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_generate_unique_number_u", lambda cursor: "ABC123NUMBER")
    monkeypatch.setenv("GATE_PHONE_WRITE_FORMAT", "sample")
    monkeypatch.delenv("GATE_PHONE_STORAGE_FORMAT", raising=False)
    cursor = _PhoneSampleCursor("+79991234567")

    identity = gate_runtime._build_identity(cursor, "Phone", "009991234567")

    assert identity.number == "009991234567"
    assert identity.phone == "+79991234567"
    assert identity.number_u == "009991234567"


def test_build_identity_for_phone_preserves_sample_phone_whitespace(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_generate_unique_number_u", lambda cursor: "ABC123NUMBER")
    monkeypatch.setenv("GATE_PHONE_WRITE_FORMAT", "sample")
    monkeypatch.delenv("GATE_PHONE_STORAGE_FORMAT", raising=False)
    cursor = _PhoneSampleCursor("89991234567\n")

    identity = gate_runtime._build_identity(cursor, "Phone", "009991234567")

    assert identity.phone == "89991234567\n"
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
        plot_number=None,
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
    assert any(sql.startswith("INSERT INTO Users") and 0 in params for sql, params in cursor.commands)


def test_insert_real_user_splits_expiry_date_and_time(monkeypatch):
    cursor = _FakeCursor()
    local_expiry = datetime(2026, 4, 13, 7, 43, 29, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)

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

    gate_runtime._insert_real_user(
        cursor,
        key_type_value=6,
        key_type="VehicleNumber",
        normalized_key_value="009991234567",
        phone_number="+79991234567",
        resident_name="Phone User",
        plot_number=None,
        is_visitor=False,
        expires_at=datetime(2026, 4, 13, 7, 43, 29, tzinfo=timezone.utc),
    )

    assert any(
        sql.startswith("INSERT INTO Users")
        and datetime.combine(local_expiry.date(), time.min) in params
        and datetime.combine(date(1899, 12, 30), local_expiry.time()) in params
        for sql, params in cursor.commands
    )


def test_insert_real_phone_user_stores_date_only_expiry(monkeypatch):
    cursor = _FakeCursor()
    local_expiry = datetime(2026, 4, 13, 7, 43, 29, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    lock_date = datetime(2026, 4, 12, 0, 0, 0)

    monkeypatch.setattr(gate_runtime, "_sample_user_defaults", lambda *args, **kwargs: {})
    monkeypatch.setattr(gate_runtime, "_access_lock_date", lambda expires_at: lock_date)
    monkeypatch.setattr(
        gate_runtime,
        "_build_identity",
        lambda *args, **kwargs: gate_runtime.RealGateIdentity(
            number="009991234567",
            phone="89991234567\n",
            number_u="009991234567",
            number_mifare=None,
        ),
    )
    monkeypatch.setattr(gate_runtime, "_resolve_inserted_user_ptr", lambda *args, **kwargs: 55)

    gate_runtime._insert_real_user(
        cursor,
        key_type_value=6,
        key_type="Phone",
        normalized_key_value="009991234567",
        phone_number="+79991234567",
        resident_name="Phone User",
        plot_number=None,
        is_visitor=False,
        expires_at=datetime(2026, 4, 13, 7, 43, 29, tzinfo=timezone.utc),
    )

    assert any(
        sql.startswith("INSERT INTO Users")
        and datetime.combine(local_expiry.date(), time.min) in params
        and datetime(1899, 12, 30, 0, 0, 0) in params
        and lock_date in params
        for sql, params in cursor.commands
    )


def test_combine_expiry_treats_sentinel_midnight_as_end_of_day():
    expiry = gate_runtime._combine_expiry(
        datetime(2026, 4, 13, 0, 0, 0),
        datetime(1899, 12, 30, 0, 0, 0),
    )

    assert expiry == datetime(2026, 4, 13, 23, 59, 59)


def test_upsert_existing_phone_user_heals_number_field(monkeypatch):
    cursor = _FakeCursor()
    observed: dict[str, object] = {}

    monkeypatch.setenv("GATE_PHONE_WRITE_FORMAT", "local_10")
    monkeypatch.delenv("GATE_PHONE_STORAGE_FORMAT", raising=False)
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 6)
    monkeypatch.setattr(gate_runtime, "_find_existing_user_ptr", lambda *args, **kwargs: 42)
    monkeypatch.setattr(gate_runtime, "_find_reusable_deleted_user_ptr", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        gate_runtime,
        "_ensure_access_permissions",
        lambda _cursor, user_ptr, access_point_ids, **kwargs: observed.setdefault(
            "ensure",
            {
                "user_ptr": user_ptr,
                "access_point_ids": list(access_point_ids),
                **kwargs,
            },
        ),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_prune_access_permissions",
        lambda _cursor, user_ptr, access_point_ids: observed.setdefault("prune", (user_ptr, list(access_point_ids))),
    )
    monkeypatch.setattr(gate_runtime, "_verify_phone_user_state", lambda *_args, **_kwargs: None)

    user_ptr = gate_runtime._upsert_real_user(
        cursor,
        key_type="Phone",
        normalized_key_value="009991234567",
        phone_number=None,
        resident_name="009991234567",
        plot_number="301",
        is_visitor=True,
        expires_at=None,
        access_point_ids=[5, 6],
    )

    assert user_ptr == 42
    assert any(
        sql == "UPDATE Users SET KeyType = ? WHERE UserPtr = ?" and params == (6, 42)
        for sql, params in cursor.commands
    )
    assert any(
        sql == "UPDATE Users SET Phone = ?, [Number] = ?, [NumberU] = ? WHERE UserPtr = ?"
        and params == ("9991234567", "009991234567", "009991234567", 42)
        for sql, params in cursor.commands
    )
    assert any(
        sql == "UPDATE Users SET [LastName] = ?, [FirstName] = ?, [FatherName] = ? WHERE UserPtr = ?"
        and params == ("009991234567", None, None, 42)
        for sql, params in cursor.commands
    )
    assert any(
        sql == "UPDATE Users SET [Details1] = ?, [Details2] = ? WHERE UserPtr = ?"
        and params == ("301", "9991234567", 42)
        for sql, params in cursor.commands
    )
    assert any(
        "SET Deleted = ?, UseExpiry = ?, ExpiryDate = ?, ExpiryTime = ?, Visitor = ?, Status = ?, LockDate = ?"
        in sql
        and params == (False, False, None, None, True, 0, None, 42)
        for sql, params in cursor.commands
    )
    assert observed["ensure"]["user_ptr"] == 42
    assert observed["ensure"]["access_point_ids"] == [5, 6]
    assert observed["ensure"]["key_type"] == "Phone"
    assert observed["prune"] == (42, [5, 6])


def test_upsert_existing_temporary_phone_user_sets_lock_date(monkeypatch):
    cursor = _FakeCursor()
    lock_date = datetime(2026, 4, 12, 0, 0, 0)

    monkeypatch.setenv("GATE_PHONE_WRITE_FORMAT", "local_10")
    monkeypatch.delenv("GATE_PHONE_STORAGE_FORMAT", raising=False)
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 6)
    monkeypatch.setattr(gate_runtime, "_find_existing_user_ptr", lambda *args, **kwargs: 42)
    monkeypatch.setattr(gate_runtime, "_find_reusable_deleted_user_ptr", lambda *args, **kwargs: None)
    monkeypatch.setattr(gate_runtime, "_access_lock_date", lambda expires_at: lock_date)
    monkeypatch.setattr(gate_runtime, "_ensure_access_permissions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_prune_access_permissions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_verify_phone_user_state", lambda *_args, **_kwargs: None)

    user_ptr = gate_runtime._upsert_real_user(
        cursor,
        key_type="Phone",
        normalized_key_value="009991234567",
        phone_number=None,
        resident_name="Phone User",
        plot_number=None,
        is_visitor=False,
        expires_at=datetime(2026, 4, 13, 7, 43, 29, tzinfo=timezone.utc),
        access_point_ids=[5, 6],
    )

    assert user_ptr == 42
    assert any(
        "SET Deleted = ?, UseExpiry = ?, ExpiryDate = ?, ExpiryTime = ?, Visitor = ?, Status = ?, LockDate = ?"
        in sql
        and params[1] is True
        and params[6] == lock_date
        and params[7] == 42
        for sql, params in cursor.commands
    )


def test_upsert_existing_phone_user_verifies_final_state(monkeypatch):
    cursor = _FakeCursor()
    observed: dict[str, object] = {}

    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 6)
    monkeypatch.setattr(gate_runtime, "_find_existing_user_ptr", lambda *args, **kwargs: 42)
    monkeypatch.setattr(gate_runtime, "_find_reusable_deleted_user_ptr", lambda *args, **kwargs: None)
    monkeypatch.setattr(gate_runtime, "_ensure_access_permissions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_prune_access_permissions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_cleanup_conflicting_phone_rows", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_apply_user_defaults", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        gate_runtime,
        "_verify_phone_user_state",
        lambda _cursor, **kwargs: observed.update(kwargs),
    )

    user_ptr = gate_runtime._upsert_real_user(
        cursor,
        key_type="Phone",
        normalized_key_value="009991234567",
        phone_number=None,
        resident_name="Phone User",
        plot_number=None,
        is_visitor=False,
        expires_at=None,
        access_point_ids=[5, 6],
    )

    assert user_ptr == 42
    assert observed == {
        "user_ptr": 42,
        "normalized_key_value": "009991234567",
        "phone_key_type_value": 6,
        "access_point_ids": [5, 6],
    }


def test_upsert_existing_vehicle_user_heals_number_u_field(monkeypatch):
    cursor = _FakeCursor()

    monkeypatch.setenv("GATE_VEHICLE_NUMBER_U_MODE", "plate")
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 3)
    monkeypatch.setattr(gate_runtime, "_find_existing_user_ptr", lambda *args, **kwargs: 42)
    monkeypatch.setattr(gate_runtime, "_find_reusable_deleted_user_ptr", lambda *args, **kwargs: None)
    monkeypatch.setattr(gate_runtime, "_ensure_access_permissions", lambda *_args, **_kwargs: None)

    user_ptr = gate_runtime._upsert_real_user(
        cursor,
        key_type="VehicleNumber",
        normalized_key_value="A123AA77",
        phone_number="+79991234567",
        resident_name="Vehicle User",
        plot_number="301",
        is_visitor=False,
        expires_at=None,
        access_point_ids=[19],
    )

    assert user_ptr == 42
    assert any(
        sql == "UPDATE Users SET [Number] = ?, [NumberU] = ? WHERE UserPtr = ?"
        and params == ("A123AA77", "A123AA77", 42)
        for sql, params in cursor.commands
    )


def test_repair_vehicle_number_u_heals_existing_vehicle_rows(monkeypatch):
    cursor = _VehicleRepairCursor(
        [
            SimpleNamespace(UserPtr=7745, KeyType=3, Number="O463OX198", NumberU="CD3005AC6563", Deleted=False),
            SimpleNamespace(UserPtr=7744, KeyType=3, Number="T581OX797", NumberU="T581OX797", Deleted=False),
            SimpleNamespace(UserPtr=7743, KeyType=6, Number="009111253128", NumberU="009111253128", Deleted=False),
            SimpleNamespace(UserPtr=7742, KeyType=3, Number="A456CD178", NumberU="5388914B2052", Deleted=True),
        ]
    )

    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 3)
    monkeypatch.setenv("GATE_VEHICLE_NUMBER_U_MODE", "plate")
    monkeypatch.setattr(gate_runtime, "_transaction_cursor", lambda: _fake_transaction_cursor(cursor))

    result = gate_runtime.repair_vehicle_number_u()

    assert result == {"scanned": 2, "updated": 1, "user_ptrs": [7745]}
    assert any(
        sql == "UPDATE Users SET [NumberU] = ? WHERE UserPtr = ?"
        and params == ("O463OX198", 7745)
        for sql, params in cursor.commands
    )


def test_insert_real_phone_user_sets_gate_details(monkeypatch):
    cursor = _FakeCursor()

    monkeypatch.setattr(gate_runtime, "_sample_user_defaults", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        gate_runtime,
        "_build_identity",
        lambda *args, **kwargs: gate_runtime.RealGateIdentity(
            number="009991234567",
            phone="89991234567\n",
            number_u="009991234567",
            number_mifare=None,
        ),
    )
    monkeypatch.setattr(gate_runtime, "_resolve_inserted_user_ptr", lambda *args, **kwargs: 55)

    gate_runtime._insert_real_user(
        cursor,
        key_type_value=6,
        key_type="Phone",
        normalized_key_value="009991234567",
        phone_number="+79991234567",
        resident_name="Phone User",
        plot_number="301",
        is_visitor=False,
        expires_at=None,
    )

    assert any(
        sql == "UPDATE Users SET [Details1] = ?, [Details2] = ? WHERE UserPtr = ?"
        and params == ("301", "89991234567", 55)
        for sql, params in cursor.commands
    )


def test_apply_user_defaults_for_existing_phone_user_uses_other_phone_template():
    cursor = _TemplateSamplingCursor(
        user_rows=[
            SimpleNamespace(
                UserPtr=42,
                GroupPtr=1,
                IdleNotLimited=False,
                NoFacility=True,
                Status=3,
                BgPtr=9,
                SendSms=False,
                SendMail=False,
                UniPassMode=5,
                Phone="89991234567\n",
                Number="009991234567",
                KeyType=6,
                Deleted=False,
            ),
            SimpleNamespace(
                UserPtr=41,
                GroupPtr=7,
                IdleNotLimited=True,
                NoFacility=False,
                Status=0,
                BgPtr=2,
                SendSms=True,
                SendMail=True,
                UniPassMode=1,
                Phone="89990001122\n",
                Number="0099990001122",
                KeyType=6,
                Deleted=False,
            ),
        ]
    )

    gate_runtime._apply_user_defaults(cursor, user_ptr=42, key_type="Phone", exclude_user_ptr=42)

    assert any(
        sql == "UPDATE Users SET [GroupPtr] = ?, [IdleNotLimited] = ?, [NoFacility] = ?, [BgPtr] = ?, [SendSms] = ?, [SendMail] = ?, [UniPassMode] = ? WHERE UserPtr = ?"
        and params == (7, True, False, 2, True, True, 1, 42)
        for sql, params in cursor.commands
    )


def test_sample_phone_user_defaults_prefers_dominant_gsm_group(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 6)
    cursor = _TemplateSamplingCursor(
        access_rows=[
            SimpleNamespace(
                UserPtr=99,
                GroupPtr=2,
                IdleNotLimited=True,
                NoFacility=True,
                BgPtr=9,
                SendSms=False,
                SendMail=False,
                UniPassMode=5,
                Phone="89991234567\n",
                Number="009991234567",
                NumberU="009991234567",
                KeyType=6,
                Deleted=False,
                Status=0,
                GsmAccessCount=2,
            ),
            SimpleNamespace(
                UserPtr=98,
                GroupPtr=1,
                IdleNotLimited=False,
                NoFacility=False,
                BgPtr=0,
                SendSms=True,
                SendMail=True,
                UniPassMode=0,
                Phone="89990001122\n",
                Number="0099990001122",
                NumberU="0099990001122",
                KeyType=6,
                Deleted=False,
                Status=0,
                GsmAccessCount=2,
            ),
            SimpleNamespace(
                UserPtr=97,
                GroupPtr=1,
                IdleNotLimited=False,
                NoFacility=False,
                BgPtr=0,
                SendSms=True,
                SendMail=True,
                UniPassMode=0,
                Phone="89990003344\n",
                Number="0099990003344",
                NumberU="0099990003344",
                KeyType=6,
                Deleted=False,
                Status=0,
                GsmAccessCount=2,
            ),
        ]
    )

    defaults = gate_runtime._sample_user_defaults(cursor, "Phone")

    assert defaults["GroupPtr"] == 1
    assert defaults["NoFacility"] is False


def test_sample_vehicle_user_defaults_prefers_dominant_nonzero_group(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 3)
    cursor = _TemplateSamplingCursor(
        access_rows=[
            SimpleNamespace(
                UserPtr=77,
                GroupPtr=0,
                IdleNotLimited=False,
                NoFacility=False,
                BgPtr=0,
                SendSms=False,
                SendMail=False,
                UniPassMode=0,
                Number="A777AA77",
                NumberU="BAD777777777",
                Phone="",
                KeyType=3,
                Deleted=False,
                Status=0,
                AccessCount=6,
            ),
            SimpleNamespace(
                UserPtr=76,
                GroupPtr=2,
                IdleNotLimited=True,
                NoFacility=False,
                BgPtr=5,
                SendSms=False,
                SendMail=False,
                UniPassMode=0,
                Number="A776AA77",
                NumberU="ABC776000000",
                Phone="89110000000",
                KeyType=3,
                Deleted=False,
                Status=0,
                AccessCount=6,
            ),
            SimpleNamespace(
                UserPtr=75,
                GroupPtr=2,
                IdleNotLimited=True,
                NoFacility=False,
                BgPtr=4,
                SendSms=False,
                SendMail=False,
                UniPassMode=0,
                Number="A775AA77",
                NumberU="ABC775000000",
                Phone="",
                KeyType=3,
                Deleted=False,
                Status=0,
                AccessCount=6,
            ),
            SimpleNamespace(
                UserPtr=74,
                GroupPtr=1,
                IdleNotLimited=False,
                NoFacility=True,
                BgPtr=1,
                SendSms=False,
                SendMail=False,
                UniPassMode=0,
                Number="A774AA77",
                NumberU="ABC774000000",
                Phone="",
                KeyType=3,
                Deleted=False,
                Status=0,
                AccessCount=6,
            ),
        ]
    )

    defaults = gate_runtime._sample_user_defaults(cursor, "VehicleNumber")

    assert defaults["GroupPtr"] == 2
    assert defaults["IdleNotLimited"] is True


def test_user_is_active_rejects_non_zero_status():
    cursor = _UserActiveCursor(
        SimpleNamespace(
            Deleted=False,
            UseExpiry=False,
            ExpiryDate=None,
            ExpiryTime=None,
            Status=2,
        )
    )

    assert gate_runtime._user_is_active(cursor, 42) is False


def test_resolve_user_ptr_matches_phone_number_without_large_userptr_lookup():
    cursor = _ResolveUserPtrCursor(
        [
            SimpleNamespace(
                UserPtr=7661,
                Phone="89111253128\n",
                Number="009111253128",
                NumberU="009111253128",
                Deleted=False,
            )
        ]
    )

    user_ptr = gate_runtime._resolve_user_ptr(cursor, "89111253128")

    assert user_ptr == 7661
    assert not any("WHERE UserPtr = ?" in sql for sql, _params in cursor.commands)


def test_normalize_phone_keeps_legacy_formats_compatible():
    assert gate_runtime._normalize_phone("8 (999) 123-45-67") == "009991234567"
    assert gate_runtime._normalize_phone("+7 999 123-45-67") == "009991234567"
    assert gate_runtime._normalize_phone("0079991234567") == "009991234567"
    assert gate_runtime._normalize_phone("9991234567") == "009991234567"


def test_normalize_vehicle_canonicalizes_lookalikes_and_separators():
    assert gate_runtime._normalize_vehicle("А 123-АА 77") == "A123AA77"


def test_normalize_vehicle_accepts_real_cyrillic_plates():
    assert gate_runtime._normalize_vehicle("\u0410 123-\u0410\u0410 77") == "A123AA77"


def test_normalize_vehicle_repairs_utf8_mojibake_before_ascii_canonicalization():
    assert gate_runtime._normalize_vehicle("\u0420\u0452123\u0420\u0452\u0420\u045277") == "A123AA77"


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
        "UPDATE AccessTable" in sql
        and params[0] == 77
        and params[9] == gate_runtime._ACCESS_RECORD_STATE_PENDING_SYNC
        and params[-2:] == (42, 70)
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
        "INSERT INTO AccessTable" in sql
        and params[:3] == (70, 42, 101)
        and params[11] == gate_runtime._ACCESS_RECORD_STATE_PENDING_SYNC
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
        "UPDATE AccessTable" in sql
        and params[0] == 101
        and params[9] == gate_runtime._ACCESS_RECORD_STATE_PENDING_SYNC
        and params[-2:] == (42, 70)
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


def test_permission_template_for_reader_uses_phone_defaults_when_no_phone_template_exists(monkeypatch):
    cursor = _TemplateSamplingCursor(
        access_rows=[
            SimpleNamespace(
                InnerNum=11,
                Always=False,
                Schedule1=True,
                Schedule2=False,
                Schedule3=False,
                Schedule4=False,
                Schedule5=False,
                Schedule6=False,
                Schedule7=False,
                RecordState=7,
                APB=True,
                Inside=True,
                CardType=3,
                CardCode="CAR",
                NoEntry=True,
                NoExit=True,
                Phone="89991234567",
                Number="A182DC178",
                KeyType=3,
                Deleted=False,
            ),
        ]
    )

    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *_args, **_kwargs: 6)

    template = gate_runtime._permission_template_for_reader(cursor, 70, key_type="Phone")

    assert template["Always"] is True
    assert template["Schedule1"] is False
    assert template["CardType"] == 0
    assert template["CardCode"] == ""


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


def test_sample_phone_storage_value_preserves_trailing_whitespace():
    cursor = _TemplateSamplingCursor(
        access_rows=[
            SimpleNamespace(
                Phone="89991234567\n",
                Number="009991234567",
                KeyType=6,
                Deleted=False,
                Name="GSM Entry",
            ),
        ]
    )

    assert gate_runtime._sample_phone_storage_value(cursor) == "89991234567\n"


def test_sample_phone_storage_value_prefers_whitespace_preserving_phone_sample():
    cursor = _TemplateSamplingCursor(
        access_rows=[
            SimpleNamespace(
                Phone="89991234567",
                Number="009991234567",
                KeyType=6,
                Deleted=False,
                Name="GSM Entry",
            ),
            SimpleNamespace(
                Phone="89990001122\n",
                Number="0099990001122",
                KeyType=6,
                Deleted=False,
                Name="GSM Exit",
            ),
        ]
    )

    assert gate_runtime._sample_phone_storage_value(cursor) == "89990001122\n"


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


def test_add_temporary_key_normalizes_naive_expiry_to_utc(monkeypatch):
    observed: dict[str, object] = {}
    cursor = _FakeCursor()

    monkeypatch.setattr(gate_runtime, "_transaction_cursor", lambda: _fake_transaction_cursor(cursor))
    monkeypatch.setattr(
        gate_runtime,
        "_upsert_real_user",
        lambda *args, **kwargs: observed.update(kwargs) or 88,
    )

    key_id = gate_runtime.add_temporary_key(
        key_type="Phone",
        key_value="+79991234567",
        phone_number="+79991234567",
        expires_at=datetime.now() + timedelta(hours=1),
        access_point_ids=[5, 6],
        resident_name="Phone User",
    )

    assert key_id == 88
    assert observed["expires_at"].tzinfo == timezone.utc
    assert observed["is_visitor"] is False


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


def test_resolve_user_ptr_matches_vehicle_number_stored_with_cyrillic_lookalikes():
    cursor = _ResolveUserPtrCursor(
        [
            SimpleNamespace(
                UserPtr=8123,
                Phone=None,
                Number="А123АА77",
                NumberU="А123АА77",
                Deleted=False,
            )
        ]
    )

    user_ptr = gate_runtime._resolve_user_ptr(cursor, "A123AA77")

    assert user_ptr == 8123


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


def test_find_existing_phone_user_ptr_matches_number_when_phone_is_empty():
    cursor = _RowCursor(
        [
            SimpleNamespace(
                UserPtr=34,
                Phone=None,
                Number="009111253128",
                NumberU="009111253128",
                KeyType=6,
                Deleted=False,
            ),
        ]
    )

    user_ptr = gate_runtime._find_existing_user_ptr(cursor, "Phone", "009111253128", key_type_value=6)

    assert user_ptr == 34


def test_cleanup_conflicting_phone_rows_deletes_other_phone_identities_and_clears_vehicle_contact_phone():
    cursor = _ConflictCleanupCursor(
        [
            SimpleNamespace(UserPtr=42, Phone="89111253128\n", Number="009111253128", KeyType=6, Deleted=False),
            SimpleNamespace(UserPtr=41, Phone="79111253128", Number="009111253128", KeyType=6, Deleted=False),
            SimpleNamespace(UserPtr=40, Phone="009111253128", Number="A182DC178", KeyType=3, Deleted=False),
            SimpleNamespace(UserPtr=39, Phone="89111253128", Number="A135BC178", KeyType=3, Deleted=True),
            SimpleNamespace(UserPtr=38, Phone=None, Number="009111253128", NumberU="009111253128", KeyType=6, Deleted=False),
        ]
    )

    gate_runtime._cleanup_conflicting_phone_rows(
        cursor,
        normalized_key_value="009111253128",
        keep_user_ptr=42,
        phone_key_type_value=6,
    )

    assert any(sql == "DELETE FROM AccessTable WHERE UserPtr = ?" and params == (41,) for sql, params in cursor.commands)
    assert any(
        "UPDATE Users" in sql
        and "PURGED" in str(params)
        and params[:6] == (True, False, None, None, None, None)
        and params[-1] == 41
        for sql, params in cursor.commands
    )
    assert any(sql == "DELETE FROM AccessTable WHERE UserPtr = ?" and params == (38,) for sql, params in cursor.commands)
    assert any(
        "UPDATE Users" in sql
        and "PURGED" in str(params)
        and params[:6] == (True, False, None, None, None, None)
        and params[-1] == 38
        for sql, params in cursor.commands
    )
    assert any(sql == "UPDATE Users SET Phone = ? WHERE UserPtr = ?" and params == (None, 40) for sql, params in cursor.commands)


def test_prune_access_permissions_keeps_only_requested_readers():
    cursor = _AccessPruneCursor(
        [
            SimpleNamespace(RdrPtr=5),
            SimpleNamespace(RdrPtr=6),
            SimpleNamespace(RdrPtr=7),
            SimpleNamespace(RdrPtr=19),
        ]
    )

    gate_runtime._prune_access_permissions(cursor, 42, [5, 6])

    assert any(
        sql == "DELETE FROM AccessTable WHERE UserPtr = ? AND RdrPtr = ?" and params == (42, 7)
        for sql, params in cursor.commands
    )
    assert any(
        sql == "DELETE FROM AccessTable WHERE UserPtr = ? AND RdrPtr = ?" and params == (42, 19)
        for sql, params in cursor.commands
    )


def test_verify_phone_user_state_accepts_expected_shape(monkeypatch):
    cursor = _PhoneVerificationCursor(
        SimpleNamespace(
            UserPtr=42,
            KeyType=6,
            Number="009111253128",
            NumberU="009111253128",
            Phone="89111253128\n",
            Deleted=False,
            Status=0,
        ),
        [
            SimpleNamespace(RdrPtr=5),
            SimpleNamespace(RdrPtr=6),
        ],
    )

    monkeypatch.setattr(gate_runtime, "_format_phone_for_storage", lambda *_args, **_kwargs: "89111253128\n")

    gate_runtime._verify_phone_user_state(
        cursor,
        user_ptr=42,
        normalized_key_value="009111253128",
        phone_key_type_value=6,
        access_point_ids=[6, 5],
    )


def test_verify_phone_user_state_raises_on_mismatch(monkeypatch):
    cursor = _PhoneVerificationCursor(
        SimpleNamespace(
            UserPtr=42,
            KeyType=3,
            Number="89111253128",
            NumberU="0F746E44BC47",
            Phone="89111253128",
            Deleted=False,
            Status=0,
        ),
        [
            SimpleNamespace(RdrPtr=5),
            SimpleNamespace(RdrPtr=6),
            SimpleNamespace(RdrPtr=19),
        ],
    )

    monkeypatch.setattr(gate_runtime, "_format_phone_for_storage", lambda *_args, **_kwargs: "89111253128\n")

    with pytest.raises(RuntimeError, match="Gate phone user verification failed"):
        gate_runtime._verify_phone_user_state(
            cursor,
            user_ptr=42,
            normalized_key_value="009111253128",
            phone_key_type_value=6,
            access_point_ids=[5, 6],
        )


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
