from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# FIX: lock file written by gate.py while a mutating gate_bridge subprocess is running.
# Guard must not open GateTerm's search dialog while gate_bridge is using the UI — doing so
# causes a race condition that triggers VB6 Error 91.
_GATE_BRIDGE_LOCK_FILE = PROJECT_ROOT / "_gate_bridge_active.lock"

from backend.app.scripts import gate_runtime  # noqa: E402

POLL_SECONDS = 0.35


def _log(message: str) -> None:
    try:
        print(message, flush=True)
    except OSError:
        pass


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Keep GateTerm users view on a safe anchor row.")
    parser.add_argument("--parent-pid", type=int, default=0, help="Backend process id. Guard exits when it disappears.")
    return parser.parse_args(argv)


def _parent_pid_is_alive(parent_pid: int) -> bool:
    if int(parent_pid) <= 0:
        return True
    if os.name == "nt":
        process_query_limited_information = 0x1000
        synchronize = 0x00100000
        desired_access = process_query_limited_information | synchronize
        handle = ctypes.windll.kernel32.OpenProcess(desired_access, False, int(parent_pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            still_active = 259
            return int(exit_code.value) == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(int(parent_pid), 0)
    except OSError:
        return False
    return True


def _configured_anchor_key_types() -> list[int]:
    raw = gate_runtime._env("GATE_GATETERM_USERS_GUARD_ANCHOR_KEY_TYPES", default="1,3,6")
    values: list[int] = []
    for part in str(raw or "").replace(";", ",").split(","):
        normalized = part.strip()
        if not normalized:
            continue
        try:
            values.append(int(normalized))
        except ValueError as exc:
            raise RuntimeError(f"Invalid GATE_GATETERM_USERS_GUARD_ANCHOR_KEY_TYPES value: {normalized!r}") from exc
    if not values:
        raise RuntimeError("GATE_GATETERM_USERS_GUARD_ANCHOR_KEY_TYPES resolved to an empty list")
    return values


def _excluded_anchor_keys() -> set[str]:
    raw = gate_runtime._env("GATE_GATETERM_USERS_GUARD_EXCLUDED_KEYS", default="")
    excluded: set[str] = set()
    for part in str(raw or "").replace(";", ",").split(","):
        normalized = str(part or "").strip()
        if normalized:
            excluded.add(normalized.casefold())
    return excluded


def _resolve_safe_anchor_key() -> str:
    configured_anchor_key = str(gate_runtime._env("GATE_GATETERM_USERS_GUARD_ANCHOR_KEY", default="") or "").strip()
    if configured_anchor_key:
        return configured_anchor_key

    excluded_anchor_keys = _excluded_anchor_keys()
    with gate_runtime._readonly_cursor() as (_, cursor):
        for key_type in _configured_anchor_key_types():
            row = cursor.execute(
                """
                SELECT TOP 1 [Number]
                FROM Users
                WHERE (Deleted = 0 OR Deleted IS NULL)
                  AND KeyType = ?
                  AND [Number] IS NOT NULL
                  AND Trim([Number]) <> ''
                ORDER BY UserPtr DESC
                """,
                (int(key_type),),
            ).fetchone()
            if row is None:
                continue
            raw_number = str(getattr(row, "Number", "") or "").strip()
            if raw_number and raw_number.casefold() not in excluded_anchor_keys:
                return raw_number
    raise RuntimeError("Failed to resolve a safe GateTerm users anchor key")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    gate_term_exe = gate_runtime._env("GATE_GATETERM_EXE", default=r"C:\GATE\Terminal\GateTerm.exe")
    if not gate_term_exe:
        raise RuntimeError("GATE_GATETERM_EXE is not configured")

    # FIX 7: grace period after any modal window was detected.
    # gate_bridge (separate process) opens + closes modal dialogs (search, edit, new-user).
    # After the modal closes, gate_bridge still needs a moment (FIX 6 settle: 0.5s, then
    # menu click, then edit window open: ~1.0s) before it can tolerate the guard running
    # its own anchor search.  If the guard opens "Поиск пользователя" inside that window,
    # VB6 raises Error 402 (can't show another modal while search is top-most).
    # Solution: after detecting ANY modal, record the time and refuse to run anchor search
    # until POST_MODAL_GRACE_SECONDS have elapsed without any modal being seen.
    POST_MODAL_GRACE_SECONDS = float(
        gate_runtime._env("GATE_GATETERM_USERS_GUARD_POST_MODAL_GRACE_SECONDS", default="2.0") or "2.0"
    )
    last_modal_seen_at: float = 0.0

    prepared_handles: set[int] = set()
    last_anchor_key = ""
    last_status = ""
    _log(f"GateTerm users guard started (parent_pid={int(args.parent_pid)})")
    application_factory = None

    while True:
        if not _parent_pid_is_alive(int(args.parent_pid)):
            _log(f"GateTerm users guard: parent pid {int(args.parent_pid)} is gone, exiting")
            return 0

        if application_factory is None:
            try:
                from pywinauto import Application as application_factory
            except ImportError as exc:
                raise RuntimeError(f"pywinauto is required for GateTerm users guard: {exc}") from exc

        try:
            app = application_factory(backend="win32").connect(path=gate_term_exe)
        except Exception:
            prepared_handles.clear()
            if last_status != "waiting_for_gateterm":
                _log("GateTerm users guard: waiting for GateTerm.exe")
                last_status = "waiting_for_gateterm"
            time.sleep(POLL_SECONDS)
            continue

        try:
            users_window = gate_runtime._find_gateterm_window(app, gate_runtime._GATETERM_USERS_WINDOW_TITLE)
            if users_window is None:
                prepared_handles.clear()
                if last_status != "waiting_for_users_window":
                    _log("GateTerm users guard: waiting for users window")
                    last_status = "waiting_for_users_window"
                time.sleep(POLL_SECONDS)
                continue

            window_handle = int(getattr(users_window, "handle", 0) or 0)
            if window_handle <= 0:
                time.sleep(POLL_SECONDS)
                continue

            if window_handle in prepared_handles:
                last_status = f"prepared:{window_handle}"
                time.sleep(POLL_SECONDS)
                continue

            # FIX 7: check for modal windows and record last-seen time
            modal_found = (
                gate_runtime._find_gateterm_window(app, gate_runtime._GATETERM_NEW_USER_WINDOW_TITLE) is not None
                or gate_runtime._find_gateterm_window(app, gate_runtime._GATETERM_USER_EDIT_WINDOW_TITLE) is not None
                or gate_runtime._find_gateterm_window(app, gate_runtime._GATETERM_USER_SEARCH_WINDOW_TITLE) is not None
                or bool(gate_runtime._gateterm_dialog_windows(app))
            )
            if modal_found:
                last_modal_seen_at = time.monotonic()
                time.sleep(POLL_SECONDS)
                continue

            # FIX 7: enforce grace period — don't run anchor search too soon after a modal
            # closed.  gate_bridge needs this window to finish opening the edit dialog
            # (FIX 6: 0.5s settle + ~0.9s for edit window = ~1.4s total).  2.0s is safe.
            if time.monotonic() - last_modal_seen_at < POST_MODAL_GRACE_SECONDS:
                time.sleep(POLL_SECONDS)
                continue

            # FIX: if gate_bridge is running a mutating UI operation, treat as "modal seen"
            # and wait — racing gate_bridge for GateTerm's UI causes VB6 Error 91.
            if _GATE_BRIDGE_LOCK_FILE.exists():
                last_modal_seen_at = time.monotonic()
                time.sleep(POLL_SECONDS)
                continue

            if not last_anchor_key:
                last_anchor_key = _resolve_safe_anchor_key()
                _log(f"GateTerm users guard: anchor key {last_anchor_key}")

            gate_runtime._search_gateterm_user_by_key_number(app, users_window, last_anchor_key)
            prepared_handles.add(window_handle)
            last_status = f"prepared:{window_handle}"
            _log(f"GateTerm users guard: prepared users window {window_handle}")
        except Exception as exc:
            prepared_handles.clear()
            last_anchor_key = ""
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            _log(f"GateTerm users guard error: {detail}")
            time.sleep(1.0)
            continue

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # pragma: no cover - production guard
        _log(f"GateTerm users guard fatal error: {exc}")
        traceback.print_exc()
        raise
