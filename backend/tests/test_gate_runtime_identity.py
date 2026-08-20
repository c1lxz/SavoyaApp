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
        if sql == "SELECT TOP 1 [Name] FROM Users":
            raise RuntimeError("Too few parameters. Expected 1.")
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def columns(self, *, table: str):
        if table != "Users":
            return []
        return [
            SimpleNamespace(column_name="LastName"),
            SimpleNamespace(column_name="FirstName"),
            SimpleNamespace(column_name="FatherName"),
        ]


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


class _PhoneRepairCursor:
    def __init__(self, rows) -> None:
        self._rows = list(rows)
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchall(self):
        if "FROM Users" in self._last_sql:
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


class _UserWithAccessRowsCursor:
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


class _ResolveUserPtrCursor:
    def __init__(self, rows) -> None:
        self._rows = list(rows)
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        if sql == "SELECT TOP 1 [Name] FROM Users" and not self.with_display_name:
            raise RuntimeError("Too few parameters. Expected 1.")
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def fetchone(self):
        if "WHERE UserPtr = ?" in self._last_sql:
            return None
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")

    def fetchall(self):
        if "SELECT UserPtr, Phone, Number, NumberU" in self._last_sql and "FROM Users" in self._last_sql:
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


class _DisplayNameRepairCursor:
    def __init__(self, rows, *, with_display_name: bool = True) -> None:
        self._rows = list(rows)
        self.with_display_name = with_display_name
        self.commands: list[tuple[str, tuple | None]] = []
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        self.commands.append((sql, tuple(params) if params is not None else None))
        return self

    def columns(self, *, table: str):
        if table != "Users":
            return []
        columns = ["LastName", "FirstName", "FatherName"]
        if self.with_display_name:
            columns.insert(0, "Name")
        return [SimpleNamespace(column_name=column_name) for column_name in columns]

    def fetchall(self):
        if "SELECT UserPtr, [Name] AS DisplayName, LastName, FirstName, FatherName, Deleted" in self._last_sql:
            return list(self._rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")


class _EventIdentityCursor:
    def __init__(self, rows, *, with_display_name: bool = True) -> None:
        self._rows = list(rows)
        self.with_display_name = with_display_name
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        if sql == "SELECT TOP 1 [Name] FROM Users" and not self.with_display_name:
            raise RuntimeError("Too few parameters. Expected 1.")
        self._last_sql = sql
        return self

    def columns(self, *, table: str):
        if table != "Users":
            return []
        columns = ["LastName", "FirstName", "FatherName", "Number", "NumberU", "Phone"]
        if self.with_display_name:
            columns.insert(0, "Name")
        return [SimpleNamespace(column_name=column_name) for column_name in columns]

    def fetchall(self):
        if "SELECT UserPtr," in self._last_sql and "LastName, FirstName, FatherName, [Number], NumberU, Phone" in self._last_sql:
            return list(self._rows)
        raise AssertionError(f"Unexpected fetchall() for SQL: {self._last_sql}")


class _AnonymousEventInferenceCursor:
    def __init__(self, *, reader_rows, user_rows, with_display_name: bool = True) -> None:
        self.reader_rows = list(reader_rows)
        self.user_rows = list(user_rows)
        self.with_display_name = with_display_name
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        if sql == "SELECT TOP 1 [Name] FROM Users" and not self.with_display_name:
            raise RuntimeError("Too few parameters. Expected 1.")
        self._last_sql = sql
        return self

    def columns(self, *, table: str):
        if table != "Users":
            return []
        columns = [
            "LastName",
            "FirstName",
            "FatherName",
            "Number",
            "NumberU",
            "Phone",
            "KeyType",
            "Deleted",
            "Status",
            "LastUsed",
            "LastUsedRdrName",
        ]
        if self.with_display_name:
            columns.insert(0, "Name")
        return [SimpleNamespace(column_name=column_name) for column_name in columns]

    def fetchall(self):
        if "SELECT RdrPtr, Name" in self._last_sql and "FROM Readers" in self._last_sql:
            return list(self.reader_rows)
        if "SELECT TOP 500" in self._last_sql and "LastUsedRdrName" in self._last_sql:
            return list(self.user_rows)
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


def test_open_access_point_via_gateterm_ui_closes_access_window_after_success(monkeypatch):
    calls: list[object] = []
    fake_app = object()

    class _FakeGrid:
        def rectangle(self):
            return SimpleNamespace(top=0, bottom=200)

        def click_input(self, *, coords):
            calls.append(("grid_click", coords))

    class _FakeButton:
        def click_input(self):
            calls.append("button_click")

    class _FakeWindow:
        def set_focus(self):
            calls.append("window_focus")

        def child_window(self, *, class_name=None, control_id=None):
            if class_name == "MSFlexGridWndClass":
                return _FakeGrid()
            if control_id == 11 and class_name == "ThunderRT6CommandButton":
                return _FakeButton()
            raise AssertionError(f"Unexpected child_window lookup: class_name={class_name!r}, control_id={control_id!r}")

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
    monkeypatch.setattr(gate_runtime, "_gateterm_ui_visible_rows", lambda cursor: [{"access_point_id": 5}])
    monkeypatch.setattr(gate_runtime, "_gateterm_ui_row_override", lambda: {})
    monkeypatch.setattr(gate_runtime, "_latest_gate_open_event", lambda access_point_id: {"index": 12})
    monkeypatch.setattr(gate_runtime, "_wait_for_gate_open_event", lambda *args, **kwargs: {"index": 13})
    monkeypatch.setattr(gate_runtime, "_open_gateterm_access_window", lambda app: _FakeWindow())
    monkeypatch.setattr(
        gate_runtime,
        "_close_gateterm_access_window_if_open",
        lambda app: calls.append(("close_access_window", app)),
    )

    result = gate_runtime._open_access_point_via_gateterm_ui(object(), 5, external_key_id="key-1")

    assert result.success is True
    assert ("close_access_window", fake_app) in calls


def test_open_access_point_via_gateterm_ui_closes_access_window_after_failure(monkeypatch):
    calls: list[object] = []
    fake_app = object()

    class _BrokenGrid:
        def rectangle(self):
            return SimpleNamespace(top=0, bottom=200)

        def click_input(self, *, coords):
            calls.append(("grid_click", coords))
            raise RuntimeError("boom")

    class _FakeButton:
        def click_input(self):
            calls.append("button_click")

    class _FakeWindow:
        def set_focus(self):
            calls.append("window_focus")

        def child_window(self, *, class_name=None, control_id=None):
            if class_name == "MSFlexGridWndClass":
                return _BrokenGrid()
            if control_id == 11 and class_name == "ThunderRT6CommandButton":
                return _FakeButton()
            raise AssertionError(f"Unexpected child_window lookup: class_name={class_name!r}, control_id={control_id!r}")

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
    monkeypatch.setattr(gate_runtime, "_gateterm_ui_visible_rows", lambda cursor: [{"access_point_id": 5}])
    monkeypatch.setattr(gate_runtime, "_gateterm_ui_row_override", lambda: {})
    monkeypatch.setattr(gate_runtime, "_latest_gate_open_event", lambda access_point_id: {"index": 12})
    monkeypatch.setattr(gate_runtime, "_open_gateterm_access_window", lambda app: _FakeWindow())
    monkeypatch.setattr(
        gate_runtime,
        "_close_gateterm_access_window_if_open",
        lambda app: calls.append(("close_access_window", app)),
    )

    result = gate_runtime._open_access_point_via_gateterm_ui(object(), 5, external_key_id="key-1")

    assert result.success is False
    assert result.error_code == "gateterm_ui_error"
    assert ("close_access_window", fake_app) in calls


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
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: calls.append("prepare_workspace"))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append("close_users"))
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
        "_populate_gateterm_vehicle_pass_editor",
        lambda window, *, normalized_key_value, resident_name: calls.append(
            ("populate_vehicle", window, normalized_key_value, resident_name)
        ),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda window, control_id, *class_names: calls.append(("click", window, control_id, class_names)),
    )
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_vehicle_user_edit_save", lambda app: calls.append(("finalize_vehicle_save", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_restore_gate_user_name_fields",
        lambda *, user_ptr, resident_name: calls.append(("restore_name", user_ptr, resident_name)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_verify_vehicle_identity_persisted",
        lambda user_ptr, normalized_key_value, expected_number_u, *, expected_resident_name=None: calls.append(
            ("verify", user_ptr, normalized_key_value, expected_number_u, expected_resident_name)
        ),
    )

    result = gate_runtime._post_sync_vehicle_key_via_gateterm_ui(
        user_ptr=42,
        normalized_key_value="A132FG777",
        expected_number_u="A132FG777",
        resident_name="Resident Vehicle",
    )

    assert result == {
        "transport": "gateterm_ui",
        "user_ptr": 42,
        "key_value": "A132FG777",
    }
    assert calls == [
        ("application_init", {"backend": "win32"}),
        ("connect", r"C:\GATE\Terminal\GateTerm.exe"),
        "prepare_workspace",
        "open_users",
        ("search", fake_users_window, "A132FG777"),
        ("open_edit", fake_users_window),
        ("collect", fake_edit_window),
        ("populate_vehicle", fake_edit_window, "A132FG777", "Resident Vehicle"),
        ("click", fake_edit_window, 1, ("ThunderRT6CommandButton", "Button")),
        ("finalize_vehicle_save", fake_app),
        ("restore_name", 42, "Resident Vehicle"),
        "close_users",
    ]


def test_search_gateterm_user_by_key_number_tolerates_window_closing_after_apply(monkeypatch):
    combo_calls: list[object] = []
    edit_calls: list[object] = []
    fake_search_window = object()

    class _FakeCombo:
        def select(self, value):
            combo_calls.append(("select", value))

    class _FakeEdit:
        def set_focus(self):
            edit_calls.append("focus")

        def set_edit_text(self, value: str):
            edit_calls.append(("set_edit_text", value))

    monkeypatch.setattr(gate_runtime, "_open_gateterm_user_search_window", lambda app, users_window: fake_search_window)
    monkeypatch.setattr(
        gate_runtime,
        "_visible_gateterm_control_by_id",
        lambda window, control_id, *class_names: _FakeCombo() if control_id == 4 else _FakeEdit(),
    )
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Handle 6227196 is not a vaild window handle")),
    )
    monkeypatch.setattr(gate_runtime, "_find_gateterm_window", lambda app, title_fragment: None)

    gate_runtime._search_gateterm_user_by_key_number(object(), object(), "X901YY799")

    assert combo_calls == [("select", gate_runtime._GATETERM_USER_SEARCH_FIELD_KEY_NUMBER_INDEX)]
    assert edit_calls == ["focus", ("set_edit_text", "X901YY799")]


def test_set_gateterm_user_key_number_updates_labeled_edit():
    edit_calls: list[object] = []

    class _FakeControl:
        def __init__(self, text: str, class_name: str) -> None:
            self._text = text
            self._class_name = class_name

        def wrapper_object(self):
            return self

        def is_visible(self):
            return True

        def window_text(self):
            return self._text

        def class_name(self):
            return self._class_name

    class _FakeEdit(_FakeControl):
        def __init__(self) -> None:
            super().__init__("", "ThunderRT6TextBox")

        def set_focus(self):
            edit_calls.append("focus")

        def set_edit_text(self, value: str):
            edit_calls.append(("set_edit_text", value))

        def type_keys(self, value: str, **_kwargs):
            edit_calls.append(("type_keys", value))

    edit = _FakeEdit()
    fake_window = SimpleNamespace(
        descendants=lambda: [
            _FakeControl("Фамилия", "ThunderRT6Label"),
            _FakeControl("Resident", "ThunderRT6TextBox"),
            _FakeControl(gate_runtime._GATETERM_USER_SEARCH_FIELD_KEY_NUMBER, "ThunderRT6Label"),
            edit,
        ]
    )

    original_sleep = gate_runtime.time_module.sleep
    gate_runtime.time_module.sleep = lambda *_args, **_kwargs: None
    try:
        gate_runtime._set_gateterm_user_key_number(fake_window, "A777AA77")
    finally:
        gate_runtime.time_module.sleep = original_sleep

    assert edit_calls == ["focus", ("set_edit_text", "A777AA77"), ("type_keys", "{TAB}")]


def test_prepare_gateterm_users_workspace_closes_dialogs_and_user_windows_in_safe_order(monkeypatch):
    calls: list[object] = []

    monkeypatch.setattr(gate_runtime, "_close_gateterm_message_boxes_if_open", lambda app: calls.append(("messages", app)))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_search_window_if_open", lambda app: calls.append(("search", app)))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_new_user_window_if_open", lambda app: calls.append(("new_user", app)))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_user_edit_window_if_open", lambda app: calls.append(("edit", app)))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append(("users", app)))

    gate_runtime._prepare_gateterm_users_workspace("app")

    assert calls == [
        ("messages", "app"),
        ("search", "app"),
        ("messages", "app"),
        ("new_user", "app"),
        ("messages", "app"),
        ("edit", "app"),
        ("messages", "app"),
        ("users", "app"),
        ("messages", "app"),
    ]


def test_close_gateterm_message_boxes_if_open_prefers_no_for_save_prompt(monkeypatch):
    calls: list[object] = []

    dialog = _FakeGateUiWindow(title="Данные пользователя изменены", class_name="#32770", handle=91)

    class _MutableFakeGateUiApp(_FakeGateUiApp):
        def close_window(self, handle: int) -> None:
            self._windows.pop(handle, None)

    app = _MutableFakeGateUiApp([dialog])
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)

    def _fake_click(window, control_id, *class_names):
        calls.append((window.handle, control_id, class_names))
        app.close_window(window.handle)

    monkeypatch.setattr(gate_runtime, "_click_gateterm_control", _fake_click)

    gate_runtime._close_gateterm_message_boxes_if_open(app)

    assert calls == [(91, 7, ("Button", "ThunderRT6CommandButton"))]


def test_confirm_gateterm_message_boxes_if_open_prefers_yes_for_save_prompt(monkeypatch):
    calls: list[object] = []

    dialog = _FakeGateUiWindow(title="Данные пользователя изменены", class_name="#32770", handle=92)

    class _MutableFakeGateUiApp(_FakeGateUiApp):
        def close_window(self, handle: int) -> None:
            self._windows.pop(handle, None)

    app = _MutableFakeGateUiApp([dialog])
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)

    def _fake_click(window, control_id, *class_names):
        calls.append((window.handle, control_id, class_names))
        app.close_window(window.handle)

    monkeypatch.setattr(gate_runtime, "_click_gateterm_control", _fake_click)

    gate_runtime._confirm_gateterm_message_boxes_if_open(app)

    assert calls == [(92, 6, ("Button", "ThunderRT6CommandButton"))]


def test_post_sync_vehicle_key_allows_gateterm_to_rewrite_number_u(monkeypatch):
    cursor = _UserActiveCursor(
        SimpleNamespace(
            UserPtr=42,
            KeyType=3,
            Number="A321BC77",
            NumberU="RANDOM123456",
            DisplayName="Resident Vehicle",
            Deleted=False,
        )
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 3)
    monkeypatch.setattr(gate_runtime, "_is_vehicle_identity_row", lambda *args, **kwargs: True)
    monkeypatch.setenv("GATE_VEHICLE_NUMBER_U_MODE", "random")
    monkeypatch.setattr(
        gate_runtime,
        "_post_sync_vehicle_key_via_gateterm_ui",
        lambda *, user_ptr, normalized_key_value, expected_number_u, resident_name: {
            "user_ptr": user_ptr,
            "key_value": normalized_key_value,
            "expected_number_u": expected_number_u,
            "resident_name": resident_name,
        },
    )

    result = gate_runtime.post_sync_vehicle_key(42)

    assert result == {
        "user_ptr": 42,
        "key_value": "A321BC77",
        "expected_number_u": None,
        "resident_name": "Resident Vehicle",
    }


def test_post_sync_vehicle_key_routes_plate_mode_through_gateterm_ui(monkeypatch):
    cursor = _UserActiveCursor(
        SimpleNamespace(
            UserPtr=42,
            KeyType=3,
            Number="A321BC77",
            NumberU="A321BC77",
            DisplayName="Resident Vehicle",
            Deleted=False,
        )
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 3)
    monkeypatch.setattr(gate_runtime, "_is_vehicle_identity_row", lambda *args, **kwargs: True)
    monkeypatch.setenv("GATE_VEHICLE_NUMBER_U_MODE", "plate")
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        gate_runtime,
        "_post_sync_vehicle_key_via_gateterm_ui",
        lambda *, user_ptr, normalized_key_value, expected_number_u, resident_name: observed.update(
            {
                "user_ptr": user_ptr,
                "normalized_key_value": normalized_key_value,
                "expected_number_u": expected_number_u,
                "resident_name": resident_name,
            }
        )
        or {
            "transport": "gateterm_ui",
            "user_ptr": user_ptr,
            "key_value": normalized_key_value,
        },
    )

    result = gate_runtime.post_sync_vehicle_key(42)

    assert result == {
        "transport": "gateterm_ui",
        "user_ptr": 42,
        "key_value": "A321BC77",
    }
    assert observed == {
        "user_ptr": 42,
        "normalized_key_value": "A321BC77",
        "expected_number_u": None,
        "resident_name": "Resident Vehicle",
    }


def test_post_sync_phone_key_routes_through_gateterm_ui(monkeypatch):
    cursor = _UserWithAccessRowsCursor(
        SimpleNamespace(
            UserPtr=42,
            KeyType=6,
            Number="009991234567",
            NumberU="009991234567",
            Phone="89991234567",
            Deleted=False,
        ),
        [
            SimpleNamespace(RdrPtr=5),
            SimpleNamespace(RdrPtr=6),
            SimpleNamespace(RdrPtr=15),
        ],
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 6)
    monkeypatch.setattr(gate_runtime, "_is_phone_identity_row", lambda *args, **kwargs: True)
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        gate_runtime,
        "_post_sync_phone_key_via_gateterm_ui",
        lambda *, user_ptr, normalized_key_value, phone_key_type_value, access_point_ids: observed.update(
            {
                "user_ptr": user_ptr,
                "normalized_key_value": normalized_key_value,
                "phone_key_type_value": phone_key_type_value,
                "access_point_ids": list(access_point_ids),
            }
        )
        or {
            "transport": "gateterm_ui",
            "user_ptr": user_ptr,
            "key_value": normalized_key_value,
        },
    )

    result = gate_runtime.post_sync_phone_key(42)

    assert result == {
        "transport": "gateterm_ui",
        "user_ptr": 42,
        "key_value": "009991234567",
    }
    assert observed == {
        "user_ptr": 42,
        "normalized_key_value": "009991234567",
        "phone_key_type_value": 6,
        "access_point_ids": [5, 6, 15],
    }


def test_verify_vehicle_identity_persisted_accepts_internal_number_u(monkeypatch):
    cursor = _UserActiveCursor(
        SimpleNamespace(
            Number="A321BC77",
            NumberU="863542F3C837",
            DisplayName="Resident Vehicle",
            LastName="Resident",
            FirstName="Vehicle",
            FatherName=None,
        )
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)

    gate_runtime._verify_vehicle_identity_persisted(
        42,
        "A321BC77",
        None,
        expected_resident_name="Resident Vehicle",
    )


def test_verify_vehicle_identity_persisted_rejects_number_u_equal_to_vehicle(monkeypatch):
    cursor = _UserActiveCursor(SimpleNamespace(Number="A321BC77", NumberU="A321BC77"))

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)

    with pytest.raises(RuntimeError, match="did not materialize"):
        gate_runtime._verify_vehicle_identity_persisted(42, "A321BC77", None)


def test_verify_vehicle_identity_persisted_rejects_missing_resident_name(monkeypatch):
    cursor = _UserActiveCursor(
        SimpleNamespace(
            Number="A321BC77",
            NumberU="863542F3C837",
            DisplayName="",
            LastName="Resident",
            FirstName="Vehicle",
            FatherName=None,
        )
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)

    with pytest.raises(RuntimeError, match="Users.Name unexpectedly"):
        gate_runtime._verify_vehicle_identity_persisted(
            42,
            "A321BC77",
            None,
            expected_resident_name="Resident Vehicle",
        )


def test_post_sync_phone_key_via_gateterm_ui_uses_clean_search_then_edit_flow(monkeypatch):
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
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: calls.append("prepare_workspace"))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append("close_users"))
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
        lambda window: calls.append(("collect", window)) or ["009991234567"],
    )
    monkeypatch.setattr(
        gate_runtime,
        "_set_gateterm_user_key_number",
        lambda window, normalized_key_value: calls.append(("set_key_number", window, normalized_key_value)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda window, control_id, *class_names: calls.append(("click", window, control_id, class_names)),
    )
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_user_edit_save", lambda app: calls.append(("finalize_save", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_verify_phone_identity_persisted",
        lambda user_ptr, normalized_key_value, phone_key_type_value, access_point_ids: calls.append(
            ("verify", user_ptr, normalized_key_value, phone_key_type_value, list(access_point_ids))
        ),
    )

    result = gate_runtime._post_sync_phone_key_via_gateterm_ui(
        user_ptr=42,
        normalized_key_value="009991234567",
        phone_key_type_value=6,
        access_point_ids=[5, 6, 15],
    )

    assert result == {
        "transport": "gateterm_ui",
        "user_ptr": 42,
        "key_value": "009991234567",
    }
    assert calls == [
        ("application_init", {"backend": "win32"}),
        ("connect", r"C:\GATE\Terminal\GateTerm.exe"),
        "prepare_workspace",
        "open_users",
        ("search", fake_users_window, "009991234567"),
        ("open_edit", fake_users_window),
        ("collect", fake_edit_window),
        ("set_key_number", fake_edit_window, "009991234567"),
        ("click", fake_edit_window, 1, ("ThunderRT6CommandButton", "Button")),
        ("finalize_save", fake_app),
        ("verify", 42, "009991234567", 6, [5, 6, 15]),
        "close_users",
    ]


def test_add_phone_permanent_key_via_gateterm_ui_creates_new_user(monkeypatch):
    calls: list[object] = []
    fake_app = object()
    fake_users_window = object()
    fake_new_window = object()
    fake_edit_window = object()

    monkeypatch.setattr(
        gate_runtime,
        "_load_phone_ui_provisioning_context",
        lambda **kwargs: {
            "existing_user_ptr": None,
            "phone_key_type_value": 6,
            "phone_storage_value": "89991234567",
            "desired_access_labels": {"калитка 1", "камера въезда", "считыватель въезд gsm"},
            "current_access_labels": set(),
        },
    )
    monkeypatch.setattr(gate_runtime, "_connect_or_start_gateterm_application", lambda: calls.append("connect") or fake_app)
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: calls.append(("prepare", app)))
    monkeypatch.setattr(gate_runtime, "_open_gateterm_users_view", lambda app: calls.append(("open_users", app)) or fake_users_window)
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append(("close_users", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_open_gateterm_new_user_window",
        lambda app, users_window: calls.append(("open_new", app, users_window)) or fake_new_window,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_search_gateterm_user_by_key_number",
        lambda app, users_window, normalized_key_value: calls.append(("search", app, users_window, normalized_key_value)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_open_gateterm_user_edit_window",
        lambda app, users_window: calls.append(("open_edit", app, users_window)) or fake_edit_window,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_populate_gateterm_phone_pass_editor",
        lambda window, **kwargs: calls.append(("populate", window, kwargs)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda window, control_id, *class_names: calls.append(("click", window, control_id, class_names)),
    )
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_new_user_save", lambda app: calls.append(("finalize_new", app)))
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_user_edit_save", lambda app: calls.append(("finalize_edit", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_wait_for_phone_user_ptr",
        lambda **kwargs: calls.append(("wait_user_ptr", kwargs)) or 9123,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_verify_phone_identity_persisted",
        lambda user_ptr, normalized_key_value, phone_key_type_value, access_point_ids: calls.append(
            ("verify", user_ptr, normalized_key_value, phone_key_type_value, list(access_point_ids))
        ),
    )

    result = gate_runtime.add_phone_permanent_key_via_gateterm_ui(
        key_value="+79991234567",
        phone_number="+79991234567",
        access_point_ids=[15, 19, 5],
        resident_name="Новый Житель",
        plot_number="11",
    )

    assert result == 9123
    assert calls == [
        "connect",
        ("prepare", fake_app),
        ("open_users", fake_app),
        ("open_new", fake_app, fake_users_window),
        (
            "populate",
            fake_new_window,
            {
                "normalized_key_value": "009991234567",
                "phone_storage_value": "89991234567",
                "resident_name": "Новый Житель",
                "plot_number": "11",
                "desired_access_labels": {"калитка 1", "камера въезда", "считыватель въезд gsm"},
                "current_access_labels": set(),
            },
        ),
        ("click", fake_new_window, 1, ("ThunderRT6CommandButton", "Button")),
        ("finalize_new", fake_app),
        (
            "wait_user_ptr",
            {
                "normalized_key_value": "009991234567",
                "phone_key_type_value": 6,
                "timeout_seconds": 12.0,
            },
        ),
        ("search", fake_app, fake_users_window, "009991234567"),
        ("open_edit", fake_app, fake_users_window),
        (
            "populate",
            fake_edit_window,
            {
                "normalized_key_value": "009991234567",
                "phone_storage_value": "89991234567",
                "resident_name": "Новый Житель",
                "plot_number": "11",
                "desired_access_labels": {"калитка 1", "камера въезда", "считыватель въезд gsm"},
                "current_access_labels": set(),
            },
        ),
        ("click", fake_edit_window, 1, ("ThunderRT6CommandButton", "Button")),
        ("finalize_edit", fake_app),
        ("verify", 9123, "009991234567", 6, [15, 19, 5]),
        ("close_users", fake_app),
    ]


def test_add_phone_permanent_key_via_gateterm_ui_updates_existing_user(monkeypatch):
    calls: list[object] = []
    fake_app = object()
    fake_users_window = object()
    fake_edit_window = object()

    monkeypatch.setattr(
        gate_runtime,
        "_load_phone_ui_provisioning_context",
        lambda **kwargs: {
            "existing_user_ptr": 3401,
            "phone_key_type_value": 6,
            "phone_storage_value": "89128152001",
            "desired_access_labels": {"считыватель въезд gsm", "считыватель выезд gsm"},
            "current_access_labels": {"считыватель въезд gsm"},
        },
    )
    monkeypatch.setattr(gate_runtime, "_connect_or_start_gateterm_application", lambda: calls.append("connect") or fake_app)
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: calls.append(("prepare", app)))
    monkeypatch.setattr(gate_runtime, "_open_gateterm_users_view", lambda app: calls.append(("open_users", app)) or fake_users_window)
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append(("close_users", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_search_gateterm_user_by_key_number",
        lambda app, users_window, normalized_key_value: calls.append(("search", app, users_window, normalized_key_value)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_open_gateterm_user_edit_window",
        lambda app, users_window: calls.append(("open_edit", app, users_window)) or fake_edit_window,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_populate_gateterm_phone_pass_editor",
        lambda window, **kwargs: calls.append(("populate", window, kwargs)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda window, control_id, *class_names: calls.append(("click", window, control_id, class_names)),
    )
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_user_edit_save", lambda app: calls.append(("finalize_edit", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_wait_for_phone_user_ptr",
        lambda **kwargs: calls.append(("wait_user_ptr", kwargs)) or 3401,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_verify_phone_identity_persisted",
        lambda user_ptr, normalized_key_value, phone_key_type_value, access_point_ids: calls.append(
            ("verify", user_ptr, normalized_key_value, phone_key_type_value, list(access_point_ids))
        ),
    )

    result = gate_runtime.add_phone_permanent_key_via_gateterm_ui(
        key_value="+79128152001",
        phone_number="+79128152001",
        access_point_ids=[5, 6],
        resident_name="Терентьева Ольга",
        plot_number="007",
    )

    assert result == 3401
    assert calls == [
        "connect",
        ("prepare", fake_app),
        ("open_users", fake_app),
        ("search", fake_app, fake_users_window, "009128152001"),
        ("open_edit", fake_app, fake_users_window),
        (
            "populate",
            fake_edit_window,
            {
                "normalized_key_value": "009128152001",
                "phone_storage_value": "89128152001",
                "resident_name": "Терентьева Ольга",
                "plot_number": "007",
                "desired_access_labels": {"считыватель въезд gsm", "считыватель выезд gsm"},
                "current_access_labels": {"считыватель въезд gsm"},
            },
        ),
        ("click", fake_edit_window, 1, ("ThunderRT6CommandButton", "Button")),
        ("finalize_edit", fake_app),
        (
            "wait_user_ptr",
            {
                "normalized_key_value": "009128152001",
                "phone_key_type_value": 6,
                "timeout_seconds": 12.0,
            },
        ),
        ("verify", 3401, "009128152001", 6, [5, 6]),
        ("close_users", fake_app),
    ]


def test_post_sync_vehicle_key_via_gateterm_ui_retries_transient_failures(monkeypatch):
    calls: list[object] = []
    fake_app = object()
    fake_users_window = object()
    fake_edit_window = object()
    state = {"search_attempts": 0}

    class _FakeApplication:
        def __init__(self, *args, **kwargs) -> None:
            calls.append(("application_init", kwargs))

        def connect(self, *, path):
            calls.append(("connect", path))
            return fake_app

    def _fake_search(app, users_window, normalized_key_value):
        state["search_attempts"] += 1
        calls.append(("search", state["search_attempts"], users_window, normalized_key_value))
        if state["search_attempts"] == 1:
            raise RuntimeError("transient search failure")

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Application=_FakeApplication))
    monkeypatch.setattr(
        gate_runtime,
        "_env",
        lambda name, *aliases, default=None, allow_empty=False: (
            "2"
            if name == "GATE_GATETERM_UI_POST_SYNC_ATTEMPTS"
            else (r"C:\GATE\Terminal\GateTerm.exe" if name == "GATE_GATETERM_EXE" else default)
        ),
    )
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: calls.append("prepare_workspace"))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append("close_users"))
    monkeypatch.setattr(gate_runtime, "_open_gateterm_users_view", lambda app: calls.append("open_users") or fake_users_window)
    monkeypatch.setattr(gate_runtime, "_search_gateterm_user_by_key_number", _fake_search)
    monkeypatch.setattr(
        gate_runtime,
        "_open_gateterm_user_edit_window",
        lambda app, users_window: calls.append(("open_edit", users_window)) or fake_edit_window,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_collect_gateterm_window_values",
        lambda window: calls.append(("collect", window)) or ["X901YY799"],
    )
    monkeypatch.setattr(
        gate_runtime,
        "_populate_gateterm_vehicle_pass_editor",
        lambda window, *, normalized_key_value, resident_name: calls.append(
            ("populate_vehicle", window, normalized_key_value, resident_name)
        ),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda window, control_id, *class_names: calls.append(("click", window, control_id, class_names)),
    )
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_vehicle_user_edit_save", lambda app: calls.append(("finalize_vehicle_save", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_restore_gate_user_name_fields",
        lambda *, user_ptr, resident_name: calls.append(("restore_name", user_ptr, resident_name)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_verify_vehicle_identity_persisted",
        lambda user_ptr, normalized_key_value, expected_number_u, *, expected_resident_name=None: calls.append(
            ("verify", user_ptr, normalized_key_value, expected_number_u, expected_resident_name)
        ),
    )

    result = gate_runtime._post_sync_vehicle_key_via_gateterm_ui(
        user_ptr=42,
        normalized_key_value="X901YY799",
        expected_number_u=None,
        resident_name="Resident Vehicle",
    )

    assert result == {
        "transport": "gateterm_ui",
        "user_ptr": 42,
        "key_value": "X901YY799",
    }
    assert state["search_attempts"] == 2
    assert ("populate_vehicle", fake_edit_window, "X901YY799", "Resident Vehicle") in calls
    assert ("finalize_vehicle_save", fake_app) in calls
    assert ("restore_name", 42, "Resident Vehicle") in calls
    assert "close_users" in calls


def test_post_sync_vehicle_key_via_gateterm_ui_retries_when_edit_window_has_other_vehicle(monkeypatch):
    calls: list[object] = []
    fake_app = object()
    fake_users_window = object()
    fake_edit_window = object()
    state = {"collect_attempts": 0}

    class _FakeApplication:
        def __init__(self, *args, **kwargs) -> None:
            calls.append(("application_init", kwargs))

        def connect(self, *, path):
            calls.append(("connect", path))
            return fake_app

    def _fake_collect(window):
        state["collect_attempts"] += 1
        calls.append(("collect", state["collect_attempts"], window))
        if state["collect_attempts"] == 1:
            return ["Z999ZZ799"]
        return ["A909BC799"]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Application=_FakeApplication))
    monkeypatch.setattr(
        gate_runtime,
        "_env",
        lambda name, *aliases, default=None, allow_empty=False: (
            "2"
            if name == "GATE_GATETERM_UI_POST_SYNC_ATTEMPTS"
            else (r"C:\GATE\Terminal\GateTerm.exe" if name == "GATE_GATETERM_EXE" else default)
        ),
    )
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: calls.append("prepare_workspace"))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append("close_users"))
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
    monkeypatch.setattr(gate_runtime, "_collect_gateterm_window_values", _fake_collect)
    monkeypatch.setattr(
        gate_runtime,
        "_populate_gateterm_vehicle_pass_editor",
        lambda window, *, normalized_key_value, resident_name: calls.append(
            ("populate_vehicle", window, normalized_key_value, resident_name)
        ),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda window, control_id, *class_names: calls.append(("click", window, control_id, class_names)),
    )
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_vehicle_user_edit_save", lambda app: calls.append(("finalize_vehicle_save", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_restore_gate_user_name_fields",
        lambda *, user_ptr, resident_name: calls.append(("restore_name", user_ptr, resident_name)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_verify_vehicle_identity_persisted",
        lambda user_ptr, normalized_key_value, expected_number_u, *, expected_resident_name=None: calls.append(
            ("verify", user_ptr, normalized_key_value, expected_number_u, expected_resident_name)
        ),
    )

    result = gate_runtime._post_sync_vehicle_key_via_gateterm_ui(
        user_ptr=7776,
        normalized_key_value="A909BC799",
        expected_number_u=None,
        resident_name="Resident Vehicle",
    )

    assert result == {
        "transport": "gateterm_ui",
        "user_ptr": 7776,
        "key_value": "A909BC799",
    }
    assert state["collect_attempts"] == 2
    assert ("populate_vehicle", fake_edit_window, "A909BC799", "Resident Vehicle") in calls
    assert ("finalize_vehicle_save", fake_app) in calls
    assert ("restore_name", 7776, "Resident Vehicle") in calls
    assert "close_users" in calls


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
        and "Phone" in params
        and "User" in params
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


def test_upsert_phone_user_purges_deleted_match_and_inserts_fresh_row(monkeypatch):
    cursor = _FakeCursor()
    observed: dict[str, object] = {}

    def _insert_real_user(*_args, **_kwargs):
        observed["insert_called"] = True
        return 77

    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 6)
    monkeypatch.setattr(gate_runtime, "_find_existing_user_ptr", lambda *args, **kwargs: None)
    monkeypatch.setattr(gate_runtime, "_find_reusable_deleted_user_ptr", lambda *args, **kwargs: 35)
    monkeypatch.setattr(
        gate_runtime,
        "_purge_deleted_phone_identity_rows",
        lambda _cursor, **kwargs: observed.setdefault("purge", kwargs.copy()),
    )
    monkeypatch.setattr(gate_runtime, "_insert_real_user", _insert_real_user)
    monkeypatch.setattr(
        gate_runtime,
        "_reactivate_real_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("deleted phone row must not be reactivated")),
    )
    monkeypatch.setattr(gate_runtime, "_cleanup_conflicting_phone_rows", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        gate_runtime,
        "_ensure_access_permissions",
        lambda _cursor, user_ptr, access_point_ids, **kwargs: observed.setdefault(
            "ensure",
            {"user_ptr": user_ptr, "access_point_ids": list(access_point_ids), **kwargs},
        ),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_prune_access_permissions",
        lambda _cursor, user_ptr, access_point_ids: observed.setdefault("prune", (user_ptr, list(access_point_ids))),
    )
    monkeypatch.setattr(gate_runtime, "_verify_phone_user_state", lambda _cursor, **kwargs: observed.setdefault("verify", kwargs))

    user_ptr = gate_runtime._upsert_real_user(
        cursor,
        key_type="Phone",
        normalized_key_value="009006342765",
        phone_number="+79006342765",
        resident_name="Fresh Phone User",
        plot_number="1111",
        is_visitor=False,
        expires_at=None,
        access_point_ids=[15, 17, 19, 20, 21, 23, 5, 6],
    )

    assert user_ptr == 77
    assert observed["purge"] == {
        "normalized_key_value": "009006342765",
        "phone_key_type_value": 6,
    }
    assert observed["insert_called"] is True
    assert observed["ensure"] == {
        "user_ptr": 77,
        "access_point_ids": [15, 17, 19, 20, 21, 23, 5, 6],
        "key_type": "Phone",
    }
    assert observed["prune"] == (77, [15, 17, 19, 20, 21, 23, 5, 6])
    assert observed["verify"] == {
        "user_ptr": 77,
        "normalized_key_value": "009006342765",
        "phone_key_type_value": 6,
        "access_point_ids": [15, 17, 19, 20, 21, 23, 5, 6],
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
    monkeypatch.setattr(gate_runtime, "_sync_user_defaults_if_needed", lambda *_args, **_kwargs: False)

    result = gate_runtime.repair_vehicle_number_u()

    assert result == {"scanned": 2, "updated": 1, "user_ptrs": [7745]}
    assert any(
        sql == "UPDATE Users SET [NumberU] = ? WHERE UserPtr = ?"
        and params == ("O463OX198", 7745)
        for sql, params in cursor.commands
    )


def test_repair_phone_identity_rows_repairs_unresolved_phone_owner_and_cleans_conflicts(monkeypatch):
    cursor = _PhoneRepairCursor(
        [
            SimpleNamespace(
                UserPtr=42,
                KeyType=6,
                Phone="",
                Number="009111253128",
                NumberU="009111253128",
                Deleted=False,
                LastUsed=datetime(2026, 5, 6, 19, 4, 22),
                LastUsedRdrName=None,
                GroupPtr=0,
            ),
            SimpleNamespace(
                UserPtr=40,
                KeyType=6,
                Phone="89111253128\n",
                Number="009111253128",
                NumberU="009111253128",
                Deleted=False,
                LastUsed=None,
                LastUsedRdrName=None,
                GroupPtr=1,
            ),
            SimpleNamespace(
                UserPtr=41,
                KeyType=3,
                Phone="009111253128",
                Number="A182DC178",
                NumberU="A182DC178",
                Deleted=False,
                LastUsed=None,
                LastUsedRdrName=None,
                GroupPtr=2,
            ),
        ]
    )
    cleanup_calls: list[tuple[str, int, int | None]] = []
    defaults_calls: list[int] = []

    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 6)
    monkeypatch.setattr(gate_runtime, "_transaction_cursor", lambda: _fake_transaction_cursor(cursor))
    monkeypatch.setattr(gate_runtime, "_format_phone_for_storage", lambda *_args, **_kwargs: "89111253128\n")
    monkeypatch.setattr(
        gate_runtime,
        "_cleanup_conflicting_phone_rows",
        lambda _cursor, *, normalized_key_value, keep_user_ptr, phone_key_type_value: cleanup_calls.append(
            (normalized_key_value, keep_user_ptr, phone_key_type_value)
        ),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_sync_user_defaults_if_needed",
        lambda _cursor, *, user_ptr, key_type, row=None, exclude_user_ptr=None: defaults_calls.append(int(user_ptr)) or True,
    )

    result = gate_runtime.repair_phone_identity_rows()

    assert result == {
        "scanned": 1,
        "updated": 1,
        "user_ptrs": [42],
        "cleaned": 1,
        "cleaned_user_ptrs": [40],
    }
    assert cleanup_calls == [("009111253128", 42, 6)]
    assert defaults_calls == [42]
    assert any(
        sql == "UPDATE Users SET [Phone] = ? WHERE UserPtr = ?"
        and params == ("89111253128\n", 42)
        for sql, params in cursor.commands
    )


def test_repair_vehicle_visual_numbers_repairs_legacy_rows_and_blank_display_names(monkeypatch):
    cursor = _VehicleRepairCursor(
        [
            SimpleNamespace(
                UserPtr=7747,
                KeyType=3,
                Number="M88FIELD1",
                NumberU="M88FIELD1",
                DisplayName="Resident Legacy",
                LastName="Resident",
                FirstName="Legacy",
                FatherName=None,
                Deleted=False,
            ),
            SimpleNamespace(
                UserPtr=7746,
                KeyType=3,
                Number="A909BC799",
                NumberU="DE41E5938A2C",
                DisplayName="",
                LastName="Resident",
                FirstName="Vehicle",
                FatherName=None,
                Deleted=False,
            ),
            SimpleNamespace(UserPtr=7745, KeyType=6, Number="009111253128", NumberU="009111253128", Deleted=False),
            SimpleNamespace(
                UserPtr=7744,
                KeyType=3,
                Number="A456CD178",
                NumberU="A456CD178",
                DisplayName="Deleted Vehicle",
                LastName="Deleted",
                FirstName="Vehicle",
                FatherName=None,
                Deleted=True,
            ),
        ]
    )
    repaired: list[int] = []

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 3)
    monkeypatch.setattr(gate_runtime, "post_sync_vehicle_key", lambda user_ptr: repaired.append(int(user_ptr)) or {"user_ptr": user_ptr})

    result = gate_runtime.repair_vehicle_visual_numbers(limit=10)

    assert result == {
        "scanned": 2,
        "updated": 2,
        "failed": 0,
        "user_ptrs": [7747, 7746],
        "failures": [],
    }
    assert repaired == [7747, 7746]


def test_repair_user_display_names_backfills_empty_name_from_split_fields(monkeypatch):
    cursor = _DisplayNameRepairCursor(
        [
            SimpleNamespace(UserPtr=9003, DisplayName="Existing Name", LastName="Ignore", FirstName="Me", FatherName=None, Deleted=False),
            SimpleNamespace(UserPtr=9002, Name="", LastName="Иванов", FirstName="Иван", FatherName="Иванович", Deleted=False),
            SimpleNamespace(UserPtr=9001, DisplayName=None, LastName=None, FirstName=None, FatherName=None, Deleted=False),
        ]
    )

    monkeypatch.setattr(gate_runtime, "_transaction_cursor", lambda: _fake_transaction_cursor(cursor))

    result = gate_runtime.repair_user_display_names()

    assert result == {"scanned": 3, "updated": 1, "user_ptrs": [9002]}
    assert any(
        sql == "UPDATE Users SET [Name] = ? WHERE UserPtr = ?"
        and params == ("Иванов Иван Иванович", 9002)
        for sql, params in cursor.commands
    )


def test_repair_user_display_names_skips_gate_schema_without_name_column(monkeypatch):
    cursor = _DisplayNameRepairCursor([], with_display_name=False)

    monkeypatch.setattr(gate_runtime, "_transaction_cursor", lambda: _fake_transaction_cursor(cursor))

    result = gate_runtime.repair_user_display_names()

    assert result == {"scanned": 0, "updated": 0, "user_ptrs": []}
    assert all("UPDATE Users SET [Name] = ?" not in sql for sql, _params in cursor.commands)


def test_load_gate_user_event_identities_reads_full_name_and_key_value(monkeypatch):
    cursor = _EventIdentityCursor(
        [
            SimpleNamespace(
                UserPtr=42,
                Name="",
                LastName="Петров",
                FirstName="Петр",
                FatherName="Петрович",
                Number="A123AA77",
                NumberU="A123AA77",
                Phone=None,
            ),
            SimpleNamespace(
                UserPtr=43,
                Name="Сидоров Сидор",
                LastName=None,
                FirstName=None,
                FatherName=None,
                Number="009991234567",
                NumberU="009991234567",
                Phone="9991234567",
            ),
        ]
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)

    identities = gate_runtime._load_gate_user_event_identities([42, 43])

    assert identities == {
        42: {
            "full_name": "Петров Петр Петрович",
            "key_type": "VehicleNumber",
            "key_value": "A123AA77",
        },
        43: {
            "full_name": "Сидоров Сидор",
            "key_type": "Phone",
            "key_value": "009991234567",
        },
    }


def test_load_gate_user_event_identities_ignores_contact_phone_on_vehicle_rows(monkeypatch):
    cursor = _EventIdentityCursor(
        [
            SimpleNamespace(
                UserPtr=52,
                Name="",
                LastName="РРІР°РЅРѕРІ",
                FirstName="РРІР°РЅ",
                FatherName=None,
                Number="A182DC178",
                NumberU="A182DC178",
                Phone="89111253128\n",
            ),
        ]
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)

    identities = gate_runtime._load_gate_user_event_identities([52])

    assert identities == {
        52: {
            "full_name": "РРІР°РЅРѕРІ РРІР°РЅ",
            "key_type": "VehicleNumber",
            "key_value": "A182DC178",
        },
    }

def test_infer_anonymous_gate_event_identities_uses_unique_recent_phone_user(monkeypatch):
    cursor = _AnonymousEventInferenceCursor(
        reader_rows=[
            SimpleNamespace(RdrPtr=6, Name="GSM Gate"),
        ],
        user_rows=[
            SimpleNamespace(
                UserPtr=7940,
                Name="",
                LastName="М",
                FirstName="Н",
                FatherName="Ю",
                Number="009006342765",
                NumberU="009006342765",
                Phone="89006342765\n",
                KeyType=6,
                Deleted=False,
                Status=0,
                LastUsed=datetime(2026, 5, 8, 17, 14, 34),
                LastUsedRdrPtr=6,
                LastUsedRdrName=None,
                LastUsedEvent="Проход по ключу разрешен",
            ),
            SimpleNamespace(
                UserPtr=7001,
                Name="",
                LastName="Старый",
                FirstName="Пользователь",
                FatherName=None,
                Number="009001112233",
                NumberU="009001112233",
                Phone="89001112233\n",
                KeyType=6,
                Deleted=False,
                Status=0,
                LastUsed=datetime(2026, 5, 8, 17, 13, 0),
                LastUsedRdrPtr=6,
                LastUsedRdrName="GSM Gate",
                LastUsedEvent="Проход по ключу разрешен",
            ),
        ],
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *_args, **_kwargs: 6)

    inferred = gate_runtime._infer_anonymous_gate_event_identities(
        [
            {
                "index": 3244,
                "time": "2026-05-08T17:14:56",
                "event_code": 8,
                "access_point_id": 6,
                "unit": "GSM Gate",
                "message": "Opened by call",
                "name": "",
                "user_ptr": 0,
                "full_name": None,
                "key_type": None,
                "key_value": None,
            }
        ]
    )

    assert inferred == {
        3244: {
            "full_name": "М Н Ю",
            "key_type": "Phone",
            "key_value": "009006342765",
            "user_ptr": 7940,
            "source": "last_used",
        }
    }


def test_infer_anonymous_gate_event_identities_skips_non_success_button_event(monkeypatch):
    cursor = _AnonymousEventInferenceCursor(
        reader_rows=[
            SimpleNamespace(RdrPtr=6, Name="GSM Gate"),
        ],
        user_rows=[
            SimpleNamespace(
                UserPtr=7940,
                Name="",
                LastName="М",
                FirstName="Н",
                FatherName="Ю",
                Number="009006342765",
                NumberU="009006342765",
                Phone="89006342765\n",
                KeyType=6,
                Deleted=False,
                Status=0,
                LastUsed=datetime(2026, 5, 8, 17, 14, 34),
                LastUsedRdrPtr=6,
                LastUsedRdrName=None,
                LastUsedEvent="Проход по ключу разрешен",
            ),
        ],
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *_args, **_kwargs: 6)

    inferred = gate_runtime._infer_anonymous_gate_event_identities(
        [
            {
                "index": 3243,
                "time": "2026-05-08T17:14:45",
                "event_code": 0,
                "access_point_id": 6,
                "unit": "GSM Gate",
                "message": "Button pressed",
                "name": "",
                "user_ptr": 0,
                "full_name": None,
                "key_type": None,
                "key_value": None,
            }
        ]
    )

    assert inferred == {}


def test_infer_anonymous_gate_event_identities_skips_ambiguous_recent_phone_users(monkeypatch):
    cursor = _AnonymousEventInferenceCursor(
        reader_rows=[
            SimpleNamespace(RdrPtr=6, Name="GSM Gate"),
        ],
        user_rows=[
            SimpleNamespace(
                UserPtr=7940,
                Name="",
                LastName="Первый",
                FirstName="Житель",
                FatherName=None,
                Number="009006342765",
                NumberU="009006342765",
                Phone="89006342765\n",
                KeyType=6,
                Deleted=False,
                Status=0,
                LastUsed=datetime(2026, 5, 8, 17, 14, 34),
                LastUsedRdrPtr=6,
                LastUsedRdrName=None,
                LastUsedEvent="Проход по ключу разрешен",
            ),
            SimpleNamespace(
                UserPtr=7941,
                Name="",
                LastName="Второй",
                FirstName="Житель",
                FatherName=None,
                Number="009001112233",
                NumberU="009001112233",
                Phone="89001112233\n",
                KeyType=6,
                Deleted=False,
                Status=0,
                LastUsed=datetime(2026, 5, 8, 17, 14, 38),
                LastUsedRdrPtr=6,
                LastUsedRdrName=None,
                LastUsedEvent="Проход по ключу разрешен",
            ),
        ],
    )

    @contextmanager
    def _fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *_args, **_kwargs: 6)

    inferred = gate_runtime._infer_anonymous_gate_event_identities(
        [
            {
                "index": 3244,
                "time": "2026-05-08T17:14:56",
                "event_code": 8,
                "access_point_id": 6,
                "unit": "GSM Gate",
                "message": "Opened by call",
                "name": "",
                "user_ptr": 0,
                "full_name": None,
                "key_type": None,
                "key_value": None,
            }
        ]
    )

    assert inferred == {}


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


def test_sync_user_defaults_if_needed_repairs_wrong_phone_group(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 6)
    current_row = SimpleNamespace(
        UserPtr=42,
        GroupPtr=2,
        IdleNotLimited=False,
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
    )
    cursor = _TemplateSamplingCursor(
        access_rows=[
            current_row,
            SimpleNamespace(
                UserPtr=41,
                GroupPtr=1,
                IdleNotLimited=True,
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
        ]
    )

    updated = gate_runtime._sync_user_defaults_if_needed(
        cursor,
        user_ptr=42,
        key_type="Phone",
        row=current_row,
        exclude_user_ptr=42,
    )

    assert updated is True
    assert any(
        sql == "UPDATE Users SET [GroupPtr] = ?, [IdleNotLimited] = ?, [NoFacility] = ?, [BgPtr] = ?, [SendSms] = ?, [SendMail] = ?, [UniPassMode] = ? WHERE UserPtr = ?"
        and params == (1, True, False, 0, True, True, 0, 42)
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


def test_sync_user_defaults_if_needed_repairs_wrong_vehicle_group(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda *args, **kwargs: 3)
    current_row = SimpleNamespace(
        UserPtr=77,
        GroupPtr=1,
        IdleNotLimited=False,
        NoFacility=True,
        BgPtr=9,
        SendSms=False,
        SendMail=False,
        UniPassMode=5,
        Phone="",
        Number="A123AA77",
        NumberU="A123AA77",
        KeyType=3,
        Deleted=False,
        Status=0,
        AccessCount=2,
    )
    cursor = _TemplateSamplingCursor(
        access_rows=[
            current_row,
            SimpleNamespace(
                UserPtr=76,
                GroupPtr=2,
                IdleNotLimited=True,
                NoFacility=False,
                BgPtr=0,
                SendSms=True,
                SendMail=True,
                UniPassMode=0,
                Phone="",
                Number="B456BB77",
                NumberU="B456BB77",
                KeyType=3,
                Deleted=False,
                Status=0,
                AccessCount=2,
            ),
        ]
    )

    updated = gate_runtime._sync_user_defaults_if_needed(
        cursor,
        user_ptr=77,
        key_type="VehicleNumber",
        row=current_row,
        exclude_user_ptr=77,
    )

    assert updated is True
    assert any(
        sql == "UPDATE Users SET [GroupPtr] = ?, [IdleNotLimited] = ?, [NoFacility] = ?, [BgPtr] = ?, [SendSms] = ?, [SendMail] = ?, [UniPassMode] = ? WHERE UserPtr = ?"
        and params == (2, True, False, 0, True, True, 0, 77)
        for sql, params in cursor.commands
    )


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


def test_resolve_user_ptr_prefers_phone_identity_over_vehicle_contact_phone():
    cursor = _ResolveUserPtrCursor(
        [
            SimpleNamespace(
                UserPtr=7662,
                Phone="89111253128\n",
                Number="A182DC178",
                NumberU="A182DC178",
                KeyType=3,
                Deleted=False,
            ),
            SimpleNamespace(
                UserPtr=7661,
                Phone="89111253128\n",
                Number="009111253128",
                NumberU="009111253128",
                KeyType=6,
                Deleted=False,
            ),
        ]
    )

    user_ptr = gate_runtime._resolve_user_ptr(cursor, "89111253128")

    assert user_ptr == 7661


def test_resolve_user_ptr_matches_gate_phone_field_when_key_numbers_are_not_phone(monkeypatch):
    monkeypatch.setattr(gate_runtime, "_sample_key_type", lambda cursor, key_type, access_point_ids=None: 6)
    cursor = _ResolveUserPtrCursor(
        [
            SimpleNamespace(
                UserPtr=7663,
                Phone="89111253128\n",
                Number="resident-legacy",
                NumberU="resident-legacy",
                KeyType=6,
                Deleted=False,
            )
        ]
    )

    user_ptr = gate_runtime._resolve_user_ptr(cursor, "+79111253128")

    assert user_ptr == 7663


def test_resolve_user_ptr_matches_phone_field_without_phone_key_type_sample(monkeypatch):
    def _sample_key_type(_cursor, key_type, access_point_ids=None):
        return 3 if key_type == "VehicleNumber" else None

    monkeypatch.setattr(gate_runtime, "_sample_key_type", _sample_key_type)
    cursor = _ResolveUserPtrCursor(
        [
            SimpleNamespace(
                UserPtr=7664,
                Phone="89111253128\n",
                Number="A182DC178",
                NumberU="A182DC178",
                KeyType=3,
                Deleted=False,
            ),
            SimpleNamespace(
                UserPtr=7665,
                Phone="89111253128\n",
                Number="resident",
                NumberU="resident",
                KeyType=6,
                Deleted=False,
            ),
        ]
    )

    user_ptr = gate_runtime._resolve_user_ptr(cursor, "+79111253128")

    assert user_ptr == 7665


def test_normalize_phone_keeps_legacy_formats_compatible():
    assert gate_runtime._normalize_phone("8 (999) 123-45-67") == "009991234567"
    assert gate_runtime._normalize_phone("+7 999 123-45-67") == "009991234567"
    assert gate_runtime._normalize_phone("0079991234567") == "009991234567"
    assert gate_runtime._normalize_phone("079819586186") == "009819586186"
    assert gate_runtime._normalize_phone("9991234567") == "009991234567"


def test_looks_like_phone_identity_number_rejects_numeric_wiegand_codes():
    assert gate_runtime._looks_like_phone_identity_number("000000458293") is False
    assert gate_runtime._looks_like_phone_identity_number("000000C8E183") is False
    assert gate_runtime._looks_like_phone_identity_number("009111253128") is True
    assert gate_runtime._looks_like_phone_identity_number("079819586186") is True


def test_normalize_vehicle_canonicalizes_lookalikes_and_separators():
    assert gate_runtime._normalize_vehicle("А 123-АА 77") == "A123AA77"


def test_normalize_vehicle_accepts_real_cyrillic_plates():
    assert gate_runtime._normalize_vehicle("\u0410 123-\u0410\u0410 77") == "A123AA77"


def test_normalize_vehicle_repairs_utf8_mojibake_before_ascii_canonicalization():
    assert gate_runtime._normalize_vehicle("\u0420\u0452123\u0420\u0452\u0420\u045277") == "A123AA77"


def test_populate_gateterm_vehicle_pass_editor_types_latin_plate(monkeypatch):
    calls = []

    monkeypatch.setattr(
        gate_runtime,
        "_visible_gateterm_control_by_id",
        lambda _window, control_id, *class_names: ("control", control_id, class_names),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_set_gateterm_text_input",
        lambda control, value, *, field_name: calls.append(("text", control, value, field_name)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_set_gateterm_combo_value",
        lambda control, value, *, field_name: calls.append(("combo", control, value, field_name)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_set_gateterm_checkbox_state",
        lambda control, value, *, field_name: calls.append(("checkbox", control, value, field_name)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_select_gateterm_user_editor_tab",
        lambda _window, tab_name: calls.append(("tab", tab_name)),
    )

    gate_runtime._populate_gateterm_vehicle_pass_editor(
        object(),
        normalized_key_value="\u0420 234 \u041e\u041a 77",
        resident_name="Resident Vehicle",
        plot_number="15",
    )

    assert ("combo", ("control", 10, ("ThunderRT6ComboBox", "ComboBox")), "Группа", "resident group") in calls
    assert ("tab", "key") in calls
    assert ("combo", ("control", 83, ("ThunderRT6ComboBox", "ComboBox")), "Номер ТС", "vehicle key type") in calls
    assert ("checkbox", ("control", 81, ("ThunderRT6CheckBox", "Button")), False, "vehicle key facility embedding") in calls
    # key number filled the same way as FIO via _set_gateterm_text_input (WM_SETTEXT)
    assert ("text", ("control", 88, ("ThunderRT6TextBox", "Edit")), "P234OK77", "vehicle key number") in calls
    assert ("tab", "info") in calls
    assert ("text", ("control", 68, ("ThunderRT6TextBox", "Edit")), "15", "resident plot number") in calls




def test_populate_gateterm_vehicle_pass_editor_skips_info_tab_without_plot_number(monkeypatch):
    calls = []

    monkeypatch.setattr(
        gate_runtime,
        "_visible_gateterm_control_by_id",
        lambda _window, control_id, *class_names: ("control", control_id, class_names),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_set_gateterm_text_input",
        lambda control, value, *, field_name: calls.append(("text", control, value, field_name)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_set_gateterm_combo_value",
        lambda control, value, *, field_name: calls.append(("combo", control, value, field_name)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_set_gateterm_checkbox_state",
        lambda control, value, *, field_name: calls.append(("checkbox", control, value, field_name)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_select_gateterm_user_editor_tab",
        lambda _window, tab_name: calls.append(("tab", tab_name)),
    )

    gate_runtime._populate_gateterm_vehicle_pass_editor(
        object(),
        normalized_key_value="A100BC77",
        resident_name="Test User",
    )

    assert ("tab", "info") not in calls
    assert not any(c[0] == "text" and isinstance(c[1], tuple) and c[1][1] == 68 for c in calls)
class _GateDeleteWaitCursor:
    def __init__(self, *, user_row, access_row) -> None:
        self.user_row = user_row
        self.access_row = access_row
        self._last_sql = ""

    def execute(self, sql: str, params=None):
        self._last_sql = sql
        return self

    def fetchone(self):
        if "FROM Users" in self._last_sql:
            return self.user_row
        if "FROM AccessTable" in self._last_sql:
            return self.access_row
        raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")


def test_wait_for_gate_user_deleted_accepts_deleted_tombstone_without_access(monkeypatch):
    cursor = _GateDeleteWaitCursor(
        user_row=SimpleNamespace(UserPtr=42, Deleted=True),
        access_row=None,
    )

    @contextmanager
    def fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", fake_readonly_cursor)

    gate_runtime._wait_for_gate_user_deleted(42, timeout_seconds=0)


def test_wait_for_gate_user_deleted_cleans_deleted_tombstone_with_access(monkeypatch):
    cursor = _GateDeleteWaitCursor(
        user_row=SimpleNamespace(UserPtr=42, Deleted=True),
        access_row=SimpleNamespace(UserPtr=42),
    )
    calls: list[tuple[str, int]] = []

    @contextmanager
    def fake_readonly_cursor():
        yield None, cursor

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", fake_readonly_cursor)
    monkeypatch.setattr(gate_runtime, "_mark_gate_user_deleted", lambda user_ptr: calls.append(("cleanup", int(user_ptr))) or True)

    gate_runtime._wait_for_gate_user_deleted(42, timeout_seconds=0)

    assert calls == [("cleanup", 42)]


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


def test_find_reusable_deleted_phone_user_ptr_reuses_deleted_gate_phone_row():
    cursor = _RowCursor(
        [
            SimpleNamespace(
                UserPtr=35,
                Phone="89006342765\n",
                Number="009006342765",
                NumberU="009006342765",
                KeyType=6,
                Deleted=True,
            ),
        ]
    )

    user_ptr = gate_runtime._find_reusable_deleted_user_ptr(cursor, "Phone", "009006342765", key_type_value=6)

    assert user_ptr == 35


def test_cleanup_conflicting_phone_rows_deletes_other_phone_identities_only():
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
    assert not any(sql == "UPDATE Users SET Phone = ? WHERE UserPtr = ?" and params == (None, 40) for sql, params in cursor.commands)


def test_purge_deleted_phone_identity_rows_scrubs_only_deleted_phone_matches():
    cursor = _ConflictCleanupCursor(
        [
            SimpleNamespace(UserPtr=52, Phone="89006342765\n", Number="009006342765", NumberU="009006342765", KeyType=6, Deleted=True),
            SimpleNamespace(UserPtr=51, Phone=None, Number="009006342765", NumberU="009006342765", KeyType=6, Deleted=True),
            SimpleNamespace(UserPtr=50, Phone="89006342765\n", Number="A135BC178", NumberU="A135BC178", KeyType=3, Deleted=True),
            SimpleNamespace(UserPtr=49, Phone="89006342765\n", Number="009006342765", NumberU="009006342765", KeyType=6, Deleted=False),
        ]
    )

    gate_runtime._purge_deleted_phone_identity_rows(
        cursor,
        normalized_key_value="009006342765",
        phone_key_type_value=6,
    )

    purged_user_ptrs = [params[0] for sql, params in cursor.commands if sql == "DELETE FROM AccessTable WHERE UserPtr = ?"]
    assert purged_user_ptrs == [52, 51]
    assert any(
        "UPDATE Users" in sql
        and "PURGED" in str(params)
        and params[-1] == 52
        for sql, params in cursor.commands
    )
    assert any(
        "UPDATE Users" in sql
        and "PURGED" in str(params)
        and params[-1] == 51
        for sql, params in cursor.commands
    )
    assert 50 not in purged_user_ptrs
    assert 49 not in purged_user_ptrs


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


def test_configure_gateterm_phone_access_uses_live_checked_state_and_preserves_gsm(monkeypatch):
    item_texts = [
        "Считыватель  калитка 1",
        "Вход Лес",
        "Вход озеро",
        "Камера Въезда",
        "Камера Выезда",
        "Считыватель Северная калитка 1",
        "Считыватель въезд GSM",
        "Считыватель выезд GSM",
    ]

    class _CheckedListBox:
        def __init__(self) -> None:
            self.checked = {6, 7}
            self.select_calls: list[tuple[int, bool]] = []

        def item_texts(self):
            return list(item_texts)

        def selected_indices(self):
            return tuple(sorted(self.checked))

        def select(self, index: int, selected: bool = True):
            self.select_calls.append((index, selected))
            if selected:
                self.checked.add(index)

        def item_rect(self, index: int):
            raise AssertionError(f"Mouse fallback was not expected for item {index}")

    listbox = _CheckedListBox()
    monkeypatch.setattr(gate_runtime, "_select_gateterm_user_editor_tab", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_visible_gateterm_control_by_id", lambda *_args, **_kwargs: listbox)
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)

    gate_runtime._configure_gateterm_phone_access_permissions(
        object(),
        desired_access_labels={
            "калитка 1",
            "калитка лес",
            "калитка озеро",
            "камера въезда",
            "камера выезда",
            "северная калитка",
        },
        # Deliberately stale: the MDB claims all six are present while the live
        # GateTerm dialog shows only the two optional GSM readers as checked.
        current_access_labels={
            "калитка 1",
            "калитка лес",
            "калитка озеро",
            "камера въезда",
            "камера выезда",
            "северная калитка",
        },
    )

    assert listbox.checked == set(range(8))
    assert listbox.select_calls == [(index, True) for index in range(6)]


def test_configure_gateterm_phone_access_uses_mouse_fallback_when_checked_state_is_unavailable(monkeypatch):
    item_texts = ["Камера Въезда", "Камера Выезда"]

    class _LegacyListBox:
        def __init__(self) -> None:
            self.clicks: list[tuple[int, int]] = []

        def item_texts(self):
            return list(item_texts)

        def selected_indices(self):
            raise RuntimeError("LB_GETSELITEMS is unavailable")

        def item_rect(self, index: int):
            return SimpleNamespace(top=index * 20, bottom=(index + 1) * 20)

        def click_input(self, *, coords):
            self.clicks.append(coords)

    listbox = _LegacyListBox()
    monkeypatch.setattr(gate_runtime, "_select_gateterm_user_editor_tab", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_visible_gateterm_control_by_id", lambda *_args, **_kwargs: listbox)
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)

    gate_runtime._configure_gateterm_phone_access_permissions(
        object(),
        desired_access_labels={"камера въезда", "камера выезда"},
        current_access_labels=set(),
    )

    assert listbox.clicks == [(8, 10), (8, 30)]


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


def test_verify_phone_user_state_accepts_extra_optional_gsm_access(monkeypatch):
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
            SimpleNamespace(RdrPtr=15),
            SimpleNamespace(RdrPtr=17),
            SimpleNamespace(RdrPtr=19),
            SimpleNamespace(RdrPtr=20),
            SimpleNamespace(RdrPtr=21),
            SimpleNamespace(RdrPtr=23),
        ],
    )
    monkeypatch.setattr(gate_runtime, "_format_phone_for_storage", lambda *_args, **_kwargs: "89111253128\n")

    gate_runtime._verify_phone_user_state(
        cursor,
        user_ptr=42,
        normalized_key_value="009111253128",
        phone_key_type_value=6,
        access_point_ids=[15, 17, 19, 20, 21, 23],
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


# ---------------------------------------------------------------------------
# _gateterm_dialog_windows
# ---------------------------------------------------------------------------


def _make_fake_window(title: str, class_name: str, handle: int):
    return SimpleNamespace(
        window_text=lambda: title,
        class_name=lambda: class_name,
        handle=handle,
    )


class _FakeApp:
    def __init__(self, windows):
        self._windows = windows
        self.captured_handles: list[int] = []

    def windows(self):
        return list(self._windows)

    def window(self, *, handle):
        self.captured_handles.append(handle)
        return SimpleNamespace(handle=handle)


def test_gateterm_dialog_windows_detects_standard_message_box():
    """#32770 class window (Win32 MessageBox) is returned as a dialog."""
    app = _FakeApp(
        [
            _make_fake_window("GateTerm", "ThunderRT6Main", 1000),
            _make_fake_window("GateTerm", "#32770", 1001),
        ]
    )

    dialogs = gate_runtime._gateterm_dialog_windows(app)

    assert len(dialogs) == 1
    assert 1001 in app.captured_handles
    assert 1000 not in app.captured_handles


def test_gateterm_dialog_windows_excludes_thunder_main_class():
    """ThunderRT6Main is always skipped regardless of window title."""
    app = _FakeApp(
        [
            _make_fake_window("GateTerm", "ThunderRT6Main", 1000),
        ]
    )

    dialogs = gate_runtime._gateterm_dialog_windows(app)

    assert dialogs == []


def test_gateterm_dialog_windows_detects_gateterm_titled_non_form_dialog():
    """A window titled 'GateTerm' that is not ThunderRT6FormDC is a dialog."""
    app = _FakeApp(
        [
            _make_fake_window("GateTerm", "#32770", 1001),
            _make_fake_window("GateTerm - Список пользователей", "ThunderRT6FormDC", 1002),
        ]
    )

    dialogs = gate_runtime._gateterm_dialog_windows(app)

    assert len(dialogs) == 1
    assert 1001 in app.captured_handles
    assert 1002 not in app.captured_handles


def test_gateterm_dialog_windows_excludes_form_dc_windows():
    """ThunderRT6FormDC class windows are not dialogs even if titled 'GateTerm'."""
    app = _FakeApp(
        [
            _make_fake_window("GateTerm", "ThunderRT6FormDC", 1003),
        ]
    )

    dialogs = gate_runtime._gateterm_dialog_windows(app)

    assert dialogs == []


def test_gateterm_dialog_windows_returns_empty_when_no_dialogs_present():
    """No dialogs and no ThunderRT6Main → empty list."""
    app = _FakeApp([])

    dialogs = gate_runtime._gateterm_dialog_windows(app)

    assert dialogs == []


# ---------------------------------------------------------------------------
# _close_gateterm_message_boxes_if_open
# ---------------------------------------------------------------------------


def test_close_gateterm_message_boxes_tries_ok_button_for_error_dialog(monkeypatch):
    """Simulates a VB6 error dialog that only has an OK button (id=1); verifies it is clicked."""
    clicked_ids: list[int] = []

    def fake_click_button(dialog, *control_ids):
        for cid in control_ids:
            if cid == 1:
                clicked_ids.append(cid)
                return True
        return False

    call_seq: list[int] = []

    def fake_dialogs(app):
        call_seq.append(len(call_seq))
        if len(call_seq) <= 1:
            return [SimpleNamespace(type_keys=lambda k: None)]
        return []

    monkeypatch.setattr(gate_runtime, "_gateterm_dialog_windows", fake_dialogs)
    monkeypatch.setattr(gate_runtime, "_click_gateterm_dialog_button", fake_click_button)

    gate_runtime._close_gateterm_message_boxes_if_open(object())

    assert 1 in clicked_ids


def test_close_gateterm_message_boxes_stops_when_no_dialogs_remain(monkeypatch):
    """Loop exits immediately when _gateterm_dialog_windows returns empty list."""
    call_count = [0]

    def fake_dialogs(app):
        call_count[0] += 1
        return []

    monkeypatch.setattr(gate_runtime, "_gateterm_dialog_windows", fake_dialogs)

    gate_runtime._close_gateterm_message_boxes_if_open(object())

    assert call_count[0] == 1


def test_close_gateterm_message_boxes_runs_up_to_four_rounds(monkeypatch):
    """With persistent dialogs the loop runs exactly 4 times then exits."""
    clicked: list[tuple] = []

    def fake_click_button(dialog, *control_ids):
        clicked.append(control_ids)
        return True

    call_count = [0]

    def fake_dialogs(app):
        call_count[0] += 1
        return [SimpleNamespace(type_keys=lambda k: None)]  # always a dialog

    monkeypatch.setattr(gate_runtime, "_gateterm_dialog_windows", fake_dialogs)
    monkeypatch.setattr(gate_runtime, "_click_gateterm_dialog_button", fake_click_button)

    gate_runtime._close_gateterm_message_boxes_if_open(object())

    assert call_count[0] == 4


# ---------------------------------------------------------------------------
# _confirm_gateterm_message_boxes_if_open
# ---------------------------------------------------------------------------


def test_confirm_gateterm_message_boxes_clicks_yes_then_ok(monkeypatch):
    """Tries button 6 (Yes) first, then 1 (OK)."""
    clicked_ids: list[int] = []

    def fake_click_button(dialog, *control_ids):
        for cid in control_ids:
            clicked_ids.extend(list(control_ids))
            return True
        return False

    call_count = [0]

    def fake_dialogs(app):
        call_count[0] += 1
        if call_count[0] <= 1:
            return [SimpleNamespace(type_keys=lambda k: None)]
        return []

    monkeypatch.setattr(gate_runtime, "_gateterm_dialog_windows", fake_dialogs)
    monkeypatch.setattr(gate_runtime, "_click_gateterm_dialog_button", fake_click_button)

    gate_runtime._confirm_gateterm_message_boxes_if_open(object())

    assert 6 in clicked_ids or 1 in clicked_ids


def test_confirm_gateterm_message_boxes_falls_back_to_enter_on_type_keys_failure(monkeypatch):
    """When button click fails AND type_keys('%Y') raises, {ENTER} is sent as final fallback."""
    enter_sent: list[str] = []

    def fake_click_button(dialog, *control_ids):
        return False

    def make_dialog():
        call_count = [0]

        def type_keys(k):
            call_count[0] += 1
            if k == "%Y":
                raise RuntimeError("type_keys failed")
            enter_sent.append(k)

        return SimpleNamespace(type_keys=type_keys)

    dialog_returned = [False]

    def fake_dialogs(app):
        if not dialog_returned[0]:
            dialog_returned[0] = True
            return [make_dialog()]
        return []

    monkeypatch.setattr(gate_runtime, "_gateterm_dialog_windows", fake_dialogs)
    monkeypatch.setattr(gate_runtime, "_click_gateterm_dialog_button", fake_click_button)

    gate_runtime._confirm_gateterm_message_boxes_if_open(object())

    assert "{ENTER}" in enter_sent


# ---------------------------------------------------------------------------
# _open_gateterm_new_user_window — error dialog detection
# ---------------------------------------------------------------------------


def test_open_gateterm_new_user_window_raises_when_error_dialog_appears(monkeypatch):
    """When GateTerm shows an error dialog instead of opening the new-user window, raises."""
    monkeypatch.setattr(gate_runtime, "_try_wait_for_gateterm_window", lambda *a, **kw: None)
    monkeypatch.setattr(gate_runtime, "_list_gateterm_windows", lambda app: [])

    dialog_obj = SimpleNamespace(type_keys=lambda k: None)
    monkeypatch.setattr(gate_runtime, "_gateterm_dialog_windows", lambda app: [dialog_obj])

    dismissed: list[bool] = []
    monkeypatch.setattr(
        gate_runtime,
        "_close_gateterm_message_boxes_if_open",
        lambda app: dismissed.append(True),
    )

    users_window = SimpleNamespace(
        set_focus=lambda: None,
        menu=lambda: SimpleNamespace(
            items=lambda: [
                SimpleNamespace(
                    sub_menu=lambda: SimpleNamespace(
                        items=lambda: [SimpleNamespace(click=lambda: None)]
                    )
                )
            ]
        ),
        type_keys=lambda k: None,
    )

    with pytest.raises(RuntimeError, match="error dialog appeared instead of new-user window"):
        gate_runtime._open_gateterm_new_user_window(object(), users_window)

    assert dismissed, "error dialog must be dismissed before raising"


def test_open_gateterm_new_user_window_dismisses_dialog_on_hotkey_attempt(monkeypatch):
    """Error dialog that appears on the hotkey (Ctrl+N) attempt is also dismissed."""
    call_count = [0]

    def fake_try_wait(app, title, *, timeout_seconds):
        # First call (menu attempt) → no dialog yet; second call (hotkey) → None
        call_count[0] += 1
        return None

    # No dialog after menu attempt; dialog appears after hotkey attempt
    menu_attempt_done = [False]

    def fake_dialog_windows(app):
        if not menu_attempt_done[0]:
            menu_attempt_done[0] = True
            return []  # no error after menu
        return [SimpleNamespace(type_keys=lambda k: None)]

    dismissed: list[bool] = []
    monkeypatch.setattr(gate_runtime, "_try_wait_for_gateterm_window", fake_try_wait)
    monkeypatch.setattr(gate_runtime, "_gateterm_dialog_windows", fake_dialog_windows)
    monkeypatch.setattr(
        gate_runtime,
        "_close_gateterm_message_boxes_if_open",
        lambda app: dismissed.append(True),
    )
    monkeypatch.setattr(gate_runtime, "_list_gateterm_windows", lambda app: [])

    users_window = SimpleNamespace(
        set_focus=lambda: None,
        menu=lambda: SimpleNamespace(
            items=lambda: [
                SimpleNamespace(
                    sub_menu=lambda: SimpleNamespace(
                        items=lambda: [SimpleNamespace(click=lambda: None)]
                    )
                )
            ]
        ),
        type_keys=lambda k: None,
    )

    with pytest.raises(RuntimeError, match="hotkey attempt"):
        gate_runtime._open_gateterm_new_user_window(object(), users_window)

    assert dismissed


def test_open_gateterm_new_user_window_returns_window_when_no_error(monkeypatch):
    """Happy path: no error dialogs, new-user window opens on first menu attempt."""
    expected_window = object()

    monkeypatch.setattr(
        gate_runtime,
        "_try_wait_for_gateterm_window",
        lambda *a, **kw: expected_window,
    )
    monkeypatch.setattr(gate_runtime, "_gateterm_dialog_windows", lambda app: [])

    users_window = SimpleNamespace(
        set_focus=lambda: None,
        menu=lambda: SimpleNamespace(
            items=lambda: [
                SimpleNamespace(
                    sub_menu=lambda: SimpleNamespace(
                        items=lambda: [SimpleNamespace(click=lambda: None)]
                    )
                )
            ]
        ),
        type_keys=lambda k: None,
    )

    result = gate_runtime._open_gateterm_new_user_window(object(), users_window)

    assert result is expected_window


# ---------------------------------------------------------------------------
# _close_gateterm_new_user_window_if_open — uses Cancel button, not WM_CLOSE
# ---------------------------------------------------------------------------


def test_close_gateterm_new_user_window_clicks_cancel_button(monkeypatch):
    """Cancel button (id=2) must be clicked, NOT WM_CLOSE/Alt+F4, to avoid VB6 Error 91."""
    clicked_controls: list[tuple] = []

    def fake_find_window(app, title_fragment):
        if gate_runtime._GATETERM_NEW_USER_WINDOW_TITLE in title_fragment:
            return SimpleNamespace(window_text=lambda: gate_runtime._GATETERM_NEW_USER_WINDOW_TITLE)
        return None

    def fake_click_control(window, control_id, *class_names):
        clicked_controls.append((control_id, class_names))

    monkeypatch.setattr(gate_runtime, "_find_gateterm_window", fake_find_window)
    monkeypatch.setattr(gate_runtime, "_click_gateterm_control", fake_click_control)
    monkeypatch.setattr(gate_runtime, "_close_gateterm_message_boxes_if_open", lambda app: None)
    monkeypatch.setattr(gate_runtime, "_window_still_open", lambda app, title: False)

    gate_runtime._close_gateterm_new_user_window_if_open(object())

    assert any(cid == 2 for cid, _ in clicked_controls), "Cancel button (id=2) must be clicked"


def test_close_gateterm_new_user_window_uses_escape_when_cancel_fails(monkeypatch):
    """Falls back to ESC when clicking Cancel raises an exception."""
    escape_sent: list[bool] = []

    def fake_find_window(app, title_fragment):
        if gate_runtime._GATETERM_NEW_USER_WINDOW_TITLE in title_fragment:
            return SimpleNamespace(window_text=lambda: gate_runtime._GATETERM_NEW_USER_WINDOW_TITLE)
        return None

    def fake_click_control(window, control_id, *class_names):
        raise RuntimeError("control not found")

    def fake_window_still_open(app, title):
        return not escape_sent  # open until ESC is sent

    def fake_dismiss_via_escape(app, title):
        escape_sent.append(True)

    monkeypatch.setattr(gate_runtime, "_find_gateterm_window", fake_find_window)
    monkeypatch.setattr(gate_runtime, "_click_gateterm_control", fake_click_control)
    monkeypatch.setattr(gate_runtime, "_close_gateterm_message_boxes_if_open", lambda app: None)
    monkeypatch.setattr(gate_runtime, "_window_still_open", fake_window_still_open)
    monkeypatch.setattr(gate_runtime, "_dismiss_gateterm_window_via_escape", fake_dismiss_via_escape)

    gate_runtime._close_gateterm_new_user_window_if_open(object())

    assert escape_sent, "ESC fallback must be used when Cancel button click fails"


def test_close_gateterm_new_user_window_skips_when_not_open(monkeypatch):
    """Does nothing when the window is not open."""
    monkeypatch.setattr(gate_runtime, "_find_gateterm_window", lambda app, title: None)
    clicked: list[bool] = []
    monkeypatch.setattr(gate_runtime, "_click_gateterm_control", lambda *a: clicked.append(True))

    gate_runtime._close_gateterm_new_user_window_if_open(object())

    assert not clicked


# ---------------------------------------------------------------------------
# _type_gateterm_field — clipboard paste, not char-by-char type_keys
# ---------------------------------------------------------------------------
def _fake_noop_cursor():
    """Cursor that silently accepts any execute() call."""

    class _Noop:
        def execute(self, sql, params=None):
            return self

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    return _Noop()


def test_add_vehicle_key_via_gateterm_ui_creates_new_user(monkeypatch):
    """New user: search is performed BEFORE clicking Add, then access-fix pass after creation."""
    calls: list[object] = []
    fake_app = object()
    fake_users_window = object()
    fake_new_window = object()
    fake_edit_window = object()

    monkeypatch.setattr(
        gate_runtime,
        "_load_vehicle_ui_provisioning_context",
        lambda **kwargs: {
            "existing_user_ptr": None,
            "vehicle_key_type_value": 3,
            "desired_access_labels": {"камера въезда", "камера выезда"},
            "current_access_labels": set(),
        },
    )
    monkeypatch.setattr(gate_runtime, "_connect_or_start_gateterm_application", lambda: calls.append("connect") or fake_app)
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: calls.append(("prepare", app)))
    monkeypatch.setattr(gate_runtime, "_open_gateterm_users_view", lambda app: calls.append(("open_users", app)) or fake_users_window)
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append(("close_users", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_search_gateterm_user_by_key_number",
        lambda app, users_window, key: calls.append(("search", app, users_window, key)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_resolve_gateterm_search_init_probe_value",
        lambda: "INIT-PROBE-FAKE",
    )
    monkeypatch.setattr(
        gate_runtime,
        "_open_gateterm_new_user_window",
        lambda app, users_window: calls.append(("open_new", app, users_window)) or fake_new_window,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_open_gateterm_user_edit_window",
        lambda app, users_window: calls.append(("open_edit", app, users_window)) or fake_edit_window,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_populate_gateterm_vehicle_pass_editor",
        lambda window, **kwargs: calls.append(("populate", window, kwargs)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda window, control_id, *class_names: calls.append(("click", window, control_id, class_names)),
    )
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_new_user_save", lambda app: calls.append(("finalize_new", app)))
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_vehicle_user_edit_save", lambda app: calls.append(("finalize_vehicle_edit", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_wait_for_vehicle_user_ptr",
        lambda **kwargs: calls.append(("wait_user_ptr", kwargs)) or 8881,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_verify_vehicle_identity_persisted",
        lambda user_ptr, key, number_u: calls.append(("verify", user_ptr, key, number_u)),
    )
    monkeypatch.setattr(gate_runtime, "_transaction_cursor", lambda: _fake_transaction_cursor(_fake_noop_cursor()))

    result = gate_runtime.add_vehicle_key_via_gateterm_ui(
        key_value="A123AA77",
        expires_at=None,
        access_point_ids=[19, 20],
        resident_name="Тест Пользователь",
        plot_number="42",
        phone_number="+79991234567",
    )

    assert result == 8881
    # search before Add is the first GateTerm action after opening the users window
    open_users_idx = calls.index(("open_users", fake_app))
    search_idx = next(i for i, c in enumerate(calls) if isinstance(c, tuple) and c[0] == "search")
    open_new_idx = next(i for i, c in enumerate(calls) if isinstance(c, tuple) and c[0] == "open_new")
    assert search_idx == open_users_idx + 1, "search must immediately follow open_users for new users"
    assert open_new_idx == search_idx + 1, "open_new must immediately follow the initial search"

    # the pre-Add search must use the resolved probe value, NOT the real plate number
    init_search = calls[search_idx]
    assert init_search[3] == "INIT-PROBE-FAKE", (
        "pre-Add search must use the resolved probe value, not the real plate number"
    )

    # populate first call uses new-user window
    first_populate = next(c for c in calls if isinstance(c, tuple) and c[0] == "populate")
    assert first_populate[1] is fake_new_window
    assert first_populate[2]["phone_number"] == "+79991234567"
    assert first_populate[2]["desired_access_labels"] == {"камера въезда", "камера выезда"}
    assert first_populate[2]["current_access_labels"] == set()

    # access fix pass happens after wait_user_ptr (current set() != desired)
    wait_idx = next(i for i, c in enumerate(calls) if isinstance(c, tuple) and c[0] == "wait_user_ptr")
    searches_after_wait = [c for c in calls[wait_idx:] if isinstance(c, tuple) and c[0] == "search"]
    assert searches_after_wait, "access fix pass must search after creation"
    edits_after_wait = [c for c in calls[wait_idx:] if isinstance(c, tuple) and c[0] == "open_edit"]
    assert edits_after_wait, "access fix pass must open edit window"

    assert ("verify", 8881, "A123AA77", None) in calls


def test_add_vehicle_key_via_gateterm_ui_updates_existing_user(monkeypatch):
    """Existing user: search then edit, access labels passed to editor, no access-fix pass."""
    calls: list[object] = []
    fake_app = object()
    fake_users_window = object()
    fake_edit_window = object()

    monkeypatch.setattr(
        gate_runtime,
        "_load_vehicle_ui_provisioning_context",
        lambda **kwargs: {
            "existing_user_ptr": 5001,
            "vehicle_key_type_value": 3,
            "desired_access_labels": {"камера въезда", "камера выезда"},
            "current_access_labels": {"камера въезда"},
        },
    )
    monkeypatch.setattr(gate_runtime, "_connect_or_start_gateterm_application", lambda: calls.append("connect") or fake_app)
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: calls.append(("prepare", app)))
    monkeypatch.setattr(gate_runtime, "_open_gateterm_users_view", lambda app: calls.append(("open_users", app)) or fake_users_window)
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append(("close_users", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_search_gateterm_user_by_key_number",
        lambda app, users_window, key: calls.append(("search", app, users_window, key)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_open_gateterm_user_edit_window",
        lambda app, users_window: calls.append(("open_edit", app, users_window)) or fake_edit_window,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_populate_gateterm_vehicle_pass_editor",
        lambda window, **kwargs: calls.append(("populate", window, kwargs)),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_click_gateterm_control",
        lambda window, control_id, *class_names: calls.append(("click", window, control_id, class_names)),
    )
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_vehicle_user_edit_save", lambda app: calls.append(("finalize_vehicle_edit", app)))
    monkeypatch.setattr(
        gate_runtime,
        "_wait_for_vehicle_user_ptr",
        lambda **kwargs: calls.append(("wait_user_ptr", kwargs)) or 5001,
    )
    monkeypatch.setattr(
        gate_runtime,
        "_verify_vehicle_identity_persisted",
        lambda user_ptr, key, number_u: calls.append(("verify", user_ptr, key, number_u)),
    )
    monkeypatch.setattr(gate_runtime, "_transaction_cursor", lambda: _fake_transaction_cursor(_fake_noop_cursor()))

    result = gate_runtime.add_vehicle_key_via_gateterm_ui(
        key_value="B456BB77",
        expires_at=None,
        access_point_ids=[19, 20],
        resident_name="Житель Существующий",
        plot_number="10",
        phone_number="+79000000001",
    )

    assert result == 5001
    # no open_new call for existing user
    assert not any(isinstance(c, tuple) and c[0] == "open_new" for c in calls)

    open_users_idx = calls.index(("open_users", fake_app))
    search_idx = next(i for i, c in enumerate(calls) if isinstance(c, tuple) and c[0] == "search")
    open_edit_idx = next(i for i, c in enumerate(calls) if isinstance(c, tuple) and c[0] == "open_edit")
    assert search_idx == open_users_idx + 1
    assert open_edit_idx == search_idx + 1

    populate_call = next(c for c in calls if isinstance(c, tuple) and c[0] == "populate")
    assert populate_call[1] is fake_edit_window
    assert populate_call[2]["desired_access_labels"] == {"камера въезда", "камера выезда"}
    assert populate_call[2]["current_access_labels"] == {"камера въезда"}
    assert populate_call[2]["phone_number"] == "+79000000001"

    # no second open_edit after wait_user_ptr (access fix not needed for existing user)
    wait_idx = next(i for i, c in enumerate(calls) if isinstance(c, tuple) and c[0] == "wait_user_ptr")
    assert not any(isinstance(c, tuple) and c[0] == "open_edit" for c in calls[wait_idx:])

    assert ("verify", 5001, "B456BB77", None) in calls


def test_add_vehicle_key_via_gateterm_ui_mdb_patch_sets_expiry_only(monkeypatch):
    """MDB patch after UI must only touch expiry/visitor/status — no phone, name, or access."""
    fake_app = object()
    fake_users_window = object()
    fake_window = object()
    mdb_cursor = _FakeCursor()

    monkeypatch.setattr(
        gate_runtime,
        "_load_vehicle_ui_provisioning_context",
        lambda **kwargs: {
            "existing_user_ptr": None,
            "vehicle_key_type_value": 3,
            "desired_access_labels": set(),
            "current_access_labels": set(),
        },
    )
    monkeypatch.setattr(gate_runtime, "_connect_or_start_gateterm_application", lambda: fake_app)
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: None)
    monkeypatch.setattr(gate_runtime, "_open_gateterm_users_view", lambda app: fake_users_window)
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: None)
    monkeypatch.setattr(gate_runtime, "_search_gateterm_user_by_key_number", lambda *a: None)
    monkeypatch.setattr(gate_runtime, "_open_gateterm_new_user_window", lambda *a: fake_window)
    monkeypatch.setattr(gate_runtime, "_populate_gateterm_vehicle_pass_editor", lambda *a, **kw: None)
    monkeypatch.setattr(gate_runtime, "_click_gateterm_control", lambda *a: None)
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate_runtime, "_finalize_gateterm_new_user_save", lambda app: None)
    monkeypatch.setattr(gate_runtime, "_wait_for_vehicle_user_ptr", lambda **kw: 9999)
    monkeypatch.setattr(gate_runtime, "_verify_vehicle_identity_persisted", lambda *a: None)
    monkeypatch.setattr(gate_runtime, "_transaction_cursor", lambda: _fake_transaction_cursor(mdb_cursor))

    gate_runtime.add_vehicle_key_via_gateterm_ui(
        key_value="C789CC99",
        expires_at=None,
        access_point_ids=[19, 20],
        resident_name="Любой Житель",
        plot_number=None,
        phone_number="+79001112233",
    )

    executed_sqls = " ".join(sql for sql, _ in mdb_cursor.commands)

    # expiry/status fields must be present
    assert "UseExpiry" in executed_sqls
    assert "Visitor" in executed_sqls
    assert "Status" in executed_sqls

    # phone, name, and access must NOT be patched via MDB
    assert "Phone" not in executed_sqls, "phone must be set via GateTerm UI, not MDB"
    assert "LastName" not in executed_sqls, "name must be set via GateTerm UI, not MDB"
    assert "AccessTable" not in executed_sqls, "access must be set via GateTerm UI, not MDB"


# ---------------------------------------------------------------------------
# _configure_gateterm_phone_access_permissions — LB_GETITEMDATA-based state
# ---------------------------------------------------------------------------


def _make_fake_access_listbox(item_names: list[str], checked_indices: set[int]):
    """Return a fake listbox whose LB_GETITEMDATA returns 1 for checked_indices."""

    class _FakeRect:
        def __init__(self, index: int):
            self.top = index * 20
            self.bottom = (index + 1) * 20

    class _FakeListbox:
        handle = 7777

        def item_texts(self):
            return list(item_names)

        def item_rect(self, index):
            return _FakeRect(index)

        def click_input(self, coords):
            _FakeListbox.clicks.append(coords)
            index = int(coords[1]) // 20
            if index in self.checked:
                self.checked.remove(index)
            else:
                self.checked.add(index)

        clicks: list = []

        def __init__(self):
            self.checked = set(checked_indices)

    _FakeListbox.clicks = []
    return _FakeListbox()


def test_configure_gateterm_phone_access_reads_actual_ui_state_via_lb_getitemdata(monkeypatch):
    """Optional existing permissions stay checked when required ones are present."""
    # UI has all three items checked (cameras + wicket)
    item_names = ["Камера Въезда", "Камера Выезда", "Калитка Север"]
    fake_lb = _make_fake_access_listbox(item_names, checked_indices={0, 1, 2})

    lb_calls: list[tuple] = []

    def _fake_lb_getitemdata(hwnd, index):
        lb_calls.append((hwnd, index))
        return 1 if index in fake_lb.checked else 0

    monkeypatch.setattr(gate_runtime, "_lb_getitemdata", _fake_lb_getitemdata)
    monkeypatch.setattr(gate_runtime, "_select_gateterm_user_editor_tab", lambda *a: None)
    monkeypatch.setattr(gate_runtime, "_visible_gateterm_control_by_id", lambda *a, **kw: fake_lb)
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_: None)

    # desired: cameras only; DB current=set() (new user) — DB state must be ignored
    gate_runtime._configure_gateterm_phone_access_permissions(
        object(),
        desired_access_labels={"камера въезда", "камера выезда"},
        current_access_labels=set(),
    )

    assert fake_lb.clicks == []
    assert fake_lb.checked == {0, 1, 2}
    assert len(lb_calls) == 3, "LB_GETITEMDATA must be called for each item"


def test_configure_gateterm_phone_access_checks_cameras_when_all_unchecked(monkeypatch):
    """When GateTerm starts with all items unchecked, check only desired cameras."""
    item_names = ["Камера Въезда", "Камера Выезда", "Калитка Север"]
    fake_lb = _make_fake_access_listbox(item_names, checked_indices=set())

    monkeypatch.setattr(
        gate_runtime,
        "_lb_getitemdata",
        lambda hwnd, index: 1 if index in fake_lb.checked else 0,
    )
    monkeypatch.setattr(gate_runtime, "_select_gateterm_user_editor_tab", lambda *a: None)
    monkeypatch.setattr(gate_runtime, "_visible_gateterm_control_by_id", lambda *a, **kw: fake_lb)
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_: None)

    gate_runtime._configure_gateterm_phone_access_permissions(
        object(),
        desired_access_labels={"камера въезда", "камера выезда"},
        current_access_labels=set(),
    )

    assert len(fake_lb.clicks) == 2, "both camera items should be checked"
    assert fake_lb.checked == {0, 1}


def test_configure_gateterm_phone_access_no_op_when_already_correct(monkeypatch):
    """No clicks when UI already matches desired state."""
    item_names = ["Камера Въезда", "Камера Выезда", "Калитка Север"]
    fake_lb = _make_fake_access_listbox(item_names, checked_indices=set())

    # UI: cameras checked, wicket unchecked
    fake_lb.checked = {0, 1}

    def _fake_lb(hwnd, index):
        return 1 if index in fake_lb.checked else 0

    monkeypatch.setattr(gate_runtime, "_lb_getitemdata", _fake_lb)
    monkeypatch.setattr(gate_runtime, "_select_gateterm_user_editor_tab", lambda *a: None)
    monkeypatch.setattr(gate_runtime, "_visible_gateterm_control_by_id", lambda *a, **kw: fake_lb)
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_: None)

    gate_runtime._configure_gateterm_phone_access_permissions(
        object(),
        desired_access_labels={"камера въезда", "камера выезда"},
        current_access_labels=set(),
    )

    assert len(fake_lb.clicks) == 0, "no clicks when UI already matches desired state"


def test_configure_gateterm_phone_access_falls_back_to_db_state_on_lb_error(monkeypatch):
    """On LB_GETITEMDATA failure, add missing required permissions only."""
    item_names = ["Камера Въезда", "Камера Выезда", "Калитка Север"]
    fake_lb = _make_fake_access_listbox(item_names, checked_indices=set())

    def _failing_lb(hwnd, index):
        raise OSError("win32 failure")

    monkeypatch.setattr(gate_runtime, "_lb_getitemdata", _failing_lb)
    monkeypatch.setattr(gate_runtime, "_select_gateterm_user_editor_tab", lambda *a: None)
    monkeypatch.setattr(gate_runtime, "_visible_gateterm_control_by_id", lambda *a, **kw: fake_lb)
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_: None)

    # DB current: wicket checked (canonical label for "Калитка Север" is "северная калитка").
    # The optional wicket is preserved while both required cameras are checked.
    gate_runtime._configure_gateterm_phone_access_permissions(
        object(),
        desired_access_labels={"камера въезда", "камера выезда"},
        current_access_labels={"северная калитка"},
    )

    assert len(fake_lb.clicks) == 2


# ---------------------------------------------------------------------------
# _remove_key_via_gateterm_ui — fast delete: search -> delete -> verify via DB,
# no user-card round-trip (which used to make deletion take minutes).
# ---------------------------------------------------------------------------


class _FakeDeleteSubItem:
    def __init__(self, calls, index):
        self._calls = calls
        self._index = index

    def click(self):
        self._calls.append(("delete_menu_click", self._index))


class _FakeDeleteSubMenu:
    def __init__(self, calls):
        self._calls = calls

    def items(self):
        return [_FakeDeleteSubItem(self._calls, i) for i in range(3)]


class _FakeDeleteTopItem:
    def __init__(self, calls):
        self._calls = calls

    def sub_menu(self):
        return _FakeDeleteSubMenu(self._calls)


class _FakeDeleteMenu:
    def __init__(self, calls):
        self._calls = calls

    def items(self):
        return [_FakeDeleteTopItem(self._calls) for _ in range(5)]


class _FakeDeleteUsersWindow:
    def __init__(self, calls, *, menu_raises=False):
        self._calls = calls
        self._menu_raises = menu_raises

    def set_focus(self):
        self._calls.append("set_focus")

    def menu(self):
        if self._menu_raises:
            raise RuntimeError("no menu")
        return _FakeDeleteMenu(self._calls)

    def type_keys(self, keys):
        self._calls.append(("type_keys", keys))


def _setup_remove_key_mocks(monkeypatch, calls, *, wait_deleted, menu_raises=False):
    fake_app = object()
    users_window = _FakeDeleteUsersWindow(calls, menu_raises=menu_raises)

    monkeypatch.setattr(gate_runtime, "_connect_or_start_gateterm_application", lambda: fake_app)
    monkeypatch.setattr(gate_runtime, "_prepare_gateterm_users_workspace", lambda app: calls.append("prepare"))
    monkeypatch.setattr(gate_runtime, "_open_gateterm_users_view", lambda app: calls.append("open_users") or users_window)
    monkeypatch.setattr(
        gate_runtime,
        "_search_gateterm_user_by_key_number",
        lambda app, window, key: calls.append(("search", key)),
    )
    # If the card-open helper is ever invoked, record it so the test can fail.
    monkeypatch.setattr(
        gate_runtime,
        "_open_gateterm_user_edit_window",
        lambda app, window: calls.append("OPEN_CARD") or object(),
    )
    monkeypatch.setattr(
        gate_runtime,
        "_wait_for_gateterm_confirmation_dialog",
        lambda app, *, timeout_seconds: calls.append("wait_dialog") or object(),
    )
    monkeypatch.setattr(gate_runtime, "_confirm_gateterm_dialog", lambda dialog: calls.append("confirm_dialog"))
    monkeypatch.setattr(gate_runtime, "_confirm_gateterm_message_boxes_if_open", lambda app: calls.append("confirm_boxes"))
    monkeypatch.setattr(gate_runtime, "_close_gateterm_users_window_if_open", lambda app: calls.append("close_users"))
    monkeypatch.setattr(gate_runtime, "_wait_for_gate_user_deleted", wait_deleted)
    monkeypatch.setattr(gate_runtime.time_module, "sleep", lambda *_a, **_kw: None)
    return fake_app, users_window


def test_remove_key_via_gateterm_ui_searches_then_deletes_without_opening_card(monkeypatch):
    calls: list = []

    def _wait_deleted(user_ptr, *, timeout_seconds):
        calls.append(("wait_deleted", int(user_ptr)))

    _setup_remove_key_mocks(monkeypatch, calls, wait_deleted=_wait_deleted)

    result = gate_runtime._remove_key_via_gateterm_ui(key_id=5001, normalized_key_value="A123BC77")

    assert result is True
    # The user card must NOT be opened — that round-trip was the slow part.
    assert "OPEN_CARD" not in calls, "deletion must not open the user card to re-verify"
    # Exactly one search, then the delete menu click.
    assert [c for c in calls if isinstance(c, tuple) and c[0] == "search"] == [("search", "A123BC77")]
    assert ("delete_menu_click", 2) in calls
    # Correctness guarantee: confirmed the exact UserPtr was deleted.
    assert ("wait_deleted", 5001) in calls


def test_remove_key_via_gateterm_ui_order_search_before_delete_before_verify(monkeypatch):
    calls: list = []

    def _wait_deleted(user_ptr, *, timeout_seconds):
        calls.append("wait_deleted")

    _setup_remove_key_mocks(monkeypatch, calls, wait_deleted=_wait_deleted)

    gate_runtime._remove_key_via_gateterm_ui(key_id=42, normalized_key_value="X1")

    search_idx = next(i for i, c in enumerate(calls) if isinstance(c, tuple) and c[0] == "search")
    delete_idx = next(i for i, c in enumerate(calls) if isinstance(c, tuple) and c[0] == "delete_menu_click")
    verify_idx = calls.index("wait_deleted")
    assert search_idx < delete_idx < verify_idx


def test_remove_key_via_gateterm_ui_falls_back_to_hotkey_when_menu_click_fails(monkeypatch):
    calls: list = []

    def _wait_deleted(user_ptr, *, timeout_seconds):
        calls.append("wait_deleted")

    _setup_remove_key_mocks(monkeypatch, calls, wait_deleted=_wait_deleted, menu_raises=True)

    result = gate_runtime._remove_key_via_gateterm_ui(key_id=7, normalized_key_value="Y2")

    assert result is True
    assert ("type_keys", "^d") in calls, "must fall back to Ctrl+D when the delete menu is unavailable"


def test_remove_key_via_gateterm_ui_retries_when_deletion_not_applied(monkeypatch):
    calls: list = []
    attempts = {"n": 0}

    def _wait_deleted(user_ptr, *, timeout_seconds):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("GateTerm did not delete key")
        calls.append("wait_deleted_ok")

    _setup_remove_key_mocks(monkeypatch, calls, wait_deleted=_wait_deleted)

    result = gate_runtime._remove_key_via_gateterm_ui(key_id=9, normalized_key_value="Z3")

    assert result is True
    # Two searches: the failed attempt plus the successful retry.
    assert len([c for c in calls if isinstance(c, tuple) and c[0] == "search"]) == 2
    assert "wait_deleted_ok" in calls


def test_wait_for_gate_user_deleted_treats_deleted_user_as_success_and_cleans_permissions(monkeypatch):
    calls: list = []

    class _DeletedUserCursor:
        def __init__(self) -> None:
            self._last_sql = ""

        def execute(self, sql: str, params=None):
            self._last_sql = sql
            calls.append(("execute", sql, tuple(params) if params is not None else None))
            return self

        def fetchone(self):
            if "FROM Users" in self._last_sql:
                return SimpleNamespace(UserPtr=42, Deleted=True)
            if "FROM AccessTable" in self._last_sql:
                return SimpleNamespace(UserPtr=42)
            raise AssertionError(f"Unexpected fetchone() for SQL: {self._last_sql}")

    @contextmanager
    def _fake_readonly_cursor():
        yield object(), _DeletedUserCursor()

    monkeypatch.setattr(gate_runtime, "_readonly_cursor", _fake_readonly_cursor)
    monkeypatch.setattr(gate_runtime, "_mark_gate_user_deleted", lambda user_ptr: calls.append(("cleanup", int(user_ptr))) or True)

    gate_runtime._wait_for_gate_user_deleted(42, timeout_seconds=0.0)

    assert ("cleanup", 42) in calls


def test_remove_key_via_gateterm_ui_raises_after_all_attempts_fail(monkeypatch):
    calls: list = []

    def _wait_deleted(user_ptr, *, timeout_seconds):
        raise RuntimeError("GateTerm did not delete key")

    _setup_remove_key_mocks(monkeypatch, calls, wait_deleted=_wait_deleted)
    monkeypatch.setattr(gate_runtime, "_env_int", lambda name, default: 3 if "DELETE_ATTEMPTS" in name else default)

    with pytest.raises(RuntimeError, match="GateTerm key deletion failed"):
        gate_runtime._remove_key_via_gateterm_ui(key_id=11, normalized_key_value="Q4")

    # Never opened the card on any attempt.
    assert "OPEN_CARD" not in calls
