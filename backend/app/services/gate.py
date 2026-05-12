from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_GATE_BRIDGE_SCRIPT = _PROJECT_ROOT / "backend" / "app" / "scripts" / "gate_bridge.py"
_GATETERM_USERS_GUARD_SCRIPT = _PROJECT_ROOT / "scripts" / "gateterm_users_guard.py"
_GATETERM_USERS_GUARD_ACTIONS = frozenset({"repair_vehicle_visual_numbers"})
_MAINTENANCE_BRIDGE_ACTIONS = frozenset(
    {
        "repair_phone_identity_rows",
        "repair_user_display_names",
        "repair_vehicle_number_u",
        "repair_vehicle_visual_numbers",
    }
)
_MUTATING_BRIDGE_ACTIONS = frozenset(
    {
        "add_permanent_key",
        "add_phone_permanent_key_via_ui",
        "add_temporary_key",
        "remove_key",
        "post_sync_phone_key",
        "repair_phone_identity_rows",
        "repair_user_display_names",
        "repair_vehicle_number_u",
        "repair_vehicle_visual_numbers",
        "post_sync_vehicle_key",
    }
)


@dataclass
class GateOpenResult:
    success: bool
    message: str
    code: str | None = None
    details: dict[str, Any] | None = None


class GateClient:
    def __init__(self) -> None:
        self._fallback_counter = 10_000
        self._gateterm_users_guard_process: Any | None = None
        self._mutating_bridge_lock = threading.Lock()

    def _next_fallback_key_id(self) -> int:
        self._fallback_counter += 1
        return self._fallback_counter

    def _should_run_gateterm_users_guard(self) -> bool:
        return bool(settings.gate_real_integration_enabled and settings.gate_gateterm_users_guard_enabled)

    @staticmethod
    def _gate_python_command(script_path: Path, *extra_args: str) -> list[str]:
        command = [settings.gate_python_launcher]
        if settings.gate_python_version:
            command.append(settings.gate_python_version)
        command.extend([str(script_path), *extra_args])
        return command

    @staticmethod
    def _gate_subprocess_env() -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        return env

    def ensure_gateterm_users_guard_running(self) -> None:
        if not self._should_run_gateterm_users_guard():
            return

        process = self._gateterm_users_guard_process
        if process is not None:
            exit_code = process.poll()
            if exit_code is None:
                return
            logger.warning("GateTerm users guard exited with code %s; restarting", exit_code)
            self._gateterm_users_guard_process = None

        if not _GATETERM_USERS_GUARD_SCRIPT.exists():
            raise RuntimeError(f"GateTerm users guard script is missing: {_GATETERM_USERS_GUARD_SCRIPT}")

        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
        self._gateterm_users_guard_process = subprocess.Popen(
            self._gate_python_command(_GATETERM_USERS_GUARD_SCRIPT, "--parent-pid", str(os.getpid())),
            cwd=_PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            env=self._gate_subprocess_env(),
            creationflags=creationflags,
        )
        logger.info(
            "Started GateTerm users guard pid=%s",
            getattr(self._gateterm_users_guard_process, "pid", None),
        )

    def stop_gateterm_users_guard(self) -> None:
        process = self._gateterm_users_guard_process
        self._gateterm_users_guard_process = None
        if process is None:
            return
        if process.poll() is not None:
            return

        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            if process.poll() is None:
                raise
            return
        logger.info("Stopped GateTerm users guard")

    def _post_sync_vehicle_key_if_needed(self, *, key_type: str, key_id: int) -> None:
        if key_type != "VehicleNumber":
            return
        self._run_bridge("post_sync_vehicle_key", {"key_id": key_id})

    def _post_sync_phone_key_if_needed(self, *, key_type: str, key_id: int) -> None:
        if key_type != "Phone":
            return
        self._run_bridge("post_sync_phone_key", {"key_id": key_id})

    def _add_real_key(self, action: str, payload: dict[str, Any], *, key_type: str) -> int:
        result = self._run_bridge(action, payload)
        key_id = int(result)
        try:
            self._post_sync_vehicle_key_if_needed(key_type=key_type, key_id=key_id)
        except Exception:
            if settings.gate_vehicle_post_sync_required:
                try:
                    self._run_bridge("remove_key", {"key_id": key_id})
                except Exception:
                    pass
                raise
            logger.warning(
                "Gate vehicle post-sync failed for key_id=%s; keeping created key because "
                "GATE_VEHICLE_POST_SYNC_REQUIRED is false",
                key_id,
                exc_info=True,
            )
        try:
            self._post_sync_phone_key_if_needed(key_type=key_type, key_id=key_id)
        except Exception:
            logger.warning(
                "Gate phone post-sync failed for key_id=%s; keeping created key in best-effort mode",
                key_id,
                exc_info=True,
            )
        return key_id

    def _add_real_account_phone_key(self, payload: dict[str, Any]) -> int:
        result = self._run_bridge("add_phone_permanent_key_via_ui", payload)
        key_id = int(result)
        if key_id <= 0:
            raise RuntimeError(f"Gate returned invalid key id: {key_id}")
        return key_id

    @staticmethod
    def _is_retryable_bridge_error(message: str) -> bool:
        normalized_message = str(message or "").lower()
        return (
            "-1102" in normalized_message
            or "-1045" in normalized_message
            or "-1206" in normalized_message
            or "-1019" in normalized_message
            or "invalid bookmark" in normalized_message
            or "locked by user" in normalized_message
            or "cannot open a database created with a previous version of your application" in normalized_message
            or "opening database failed" in normalized_message
            or "открытие базы данных" in normalized_message
            or "недопустимая закладка" in normalized_message
            or "блокиров" in normalized_message
        )

    @staticmethod
    def _bridge_timeout_seconds(action: str) -> int:
        if action in {"post_sync_vehicle_key", "post_sync_phone_key", "add_phone_permanent_key_via_ui"}:
            return max(1, int(settings.gate_bridge_vehicle_post_sync_timeout_seconds))
        if action in _MAINTENANCE_BRIDGE_ACTIONS:
            return max(1, int(settings.gate_bridge_maintenance_timeout_seconds))
        return max(1, int(settings.gate_bridge_timeout_seconds))

    def _run_bridge(self, action: str, payload: dict[str, Any] | None = None) -> Any:
        if action in _GATETERM_USERS_GUARD_ACTIONS:
            self.ensure_gateterm_users_guard_running()

        command = self._gate_python_command(_GATE_BRIDGE_SCRIPT, action)
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        attempts = max(1, int(settings.gate_bridge_retry_attempts))
        delay_seconds = max(0.0, float(settings.gate_bridge_retry_delay_seconds))
        timeout_seconds = self._bridge_timeout_seconds(action)
        maintenance_action = action in _MAINTENANCE_BRIDGE_ACTIONS

        bridge_lock = self._mutating_bridge_lock if action in _MUTATING_BRIDGE_ACTIONS else nullcontext()
        with bridge_lock:
            deadline = time.monotonic() + timeout_seconds if maintenance_action else None
            attempt_index = 0
            while True:
                attempt_index += 1
                attempt_timeout = timeout_seconds
                if deadline is not None:
                    remaining_before_attempt = deadline - time.monotonic()
                    if remaining_before_attempt <= 0:
                        raise RuntimeError(
                            f"Gate bridge action '{action}' timed out after {timeout_seconds} seconds"
                        )
                    attempt_timeout = max(1, min(timeout_seconds, int(remaining_before_attempt)))
                try:
                    completed = subprocess.run(
                        command,
                        cwd=_PROJECT_ROOT,
                        input=payload_json,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        env=self._gate_subprocess_env(),
                        timeout=attempt_timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError(f"Gate bridge action '{action}' timed out after {timeout_seconds} seconds") from exc
                stdout = (completed.stdout or "").strip()
                stderr = (completed.stderr or "").strip()
                if completed.returncode == 0:
                    try:
                        data = json.loads(stdout)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(f"Gate bridge returned invalid JSON: {stdout}") from exc

                    if not data.get("ok"):
                        raise RuntimeError(str(data.get("error") or "Gate bridge failed"))
                    return data.get("result")

                message = stdout or stderr or f"Gate bridge failed with exit code {completed.returncode}"
                if deadline is not None:
                    is_last_attempt = time.monotonic() >= deadline
                else:
                    is_last_attempt = attempt_index >= attempts
                if is_last_attempt or not self._is_retryable_bridge_error(message):
                    raise RuntimeError(message)
                if deadline is None:
                    time.sleep(delay_seconds)
                    continue
                remaining_after_attempt = deadline - time.monotonic()
                if remaining_after_attempt <= 0:
                    raise RuntimeError(message)
                time.sleep(min(delay_seconds, remaining_after_attempt))

        raise RuntimeError("Gate bridge retry loop exited unexpectedly")

    def add_temporary_key(
        self,
        key_type: str,
        key_value: str,
        phone_number: str | None,
        expires_at: datetime,
        access_point_ids: list[int],
        resident_name: str,
        plot_number: str | None = None,
    ) -> int:
        if settings.gate_real_integration_enabled:
            return self._add_real_key(
                "add_temporary_key",
                {
                    "key_type": key_type,
                    "key_value": key_value,
                    "phone_number": phone_number,
                    "expires_at": expires_at.isoformat(),
                    "access_point_ids": access_point_ids,
                    "resident_name": resident_name,
                    "plot_number": plot_number,
                },
                key_type=key_type,
            )
        return self._next_fallback_key_id()

    def add_permanent_key(
        self,
        key_type: str,
        key_value: str,
        phone_number: str | None,
        access_point_ids: list[int],
        resident_name: str,
        plot_number: str | None = None,
    ) -> int:
        if settings.gate_real_integration_enabled:
            return self._add_real_key(
                "add_permanent_key",
                {
                    "key_type": key_type,
                    "key_value": key_value,
                    "phone_number": phone_number,
                    "access_point_ids": access_point_ids,
                    "resident_name": resident_name,
                    "plot_number": plot_number,
                },
                key_type=key_type,
            )
        return self._next_fallback_key_id()

    def add_account_phone_key(
        self,
        *,
        key_value: str,
        phone_number: str | None,
        access_point_ids: list[int],
        resident_name: str,
        plot_number: str | None = None,
    ) -> int:
        if settings.gate_real_integration_enabled:
            return self._add_real_account_phone_key(
                {
                    "key_value": key_value,
                    "phone_number": phone_number,
                    "access_point_ids": access_point_ids,
                    "resident_name": resident_name,
                    "plot_number": plot_number,
                }
            )
        return self._next_fallback_key_id()

    def remove_key(self, key_id: int) -> bool:
        if settings.gate_real_integration_enabled:
            return bool(self._run_bridge("remove_key", {"key_id": key_id}))
        return True

    def resolve_key_id(self, external_key_id: str) -> int | None:
        if settings.gate_real_integration_enabled:
            result = self._run_bridge("resolve_key_id", {"external_key_id": external_key_id})
            if result is None:
                return None
            resolved = int(result)
            return resolved if resolved > 0 else None
        return None

    def get_access_points(self) -> list[dict[str, Any]]:
        if settings.gate_real_integration_enabled:
            result = self._run_bridge("get_access_points")
            return [dict(item) for item in result]

        action_map = settings.gate_action_map
        reverse_map = {value: key for key, value in action_map.items()}
        points = []
        for point_id in sorted(reverse_map):
            points.append({"id": point_id, "name": reverse_map[point_id]})
        return points

    def get_recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        if settings.gate_real_integration_enabled:
            result = self._run_bridge("get_recent_events", {"limit": safe_limit})
            return [dict(item) for item in result]
        return []

    def repair_user_display_names(self) -> dict[str, Any]:
        if settings.gate_real_integration_enabled:
            result = self._run_bridge("repair_user_display_names")
            return dict(result or {})
        return {"scanned": 0, "updated": 0, "user_ptrs": []}

    def repair_phone_identity_rows(self) -> dict[str, Any]:
        if settings.gate_real_integration_enabled:
            result = self._run_bridge("repair_phone_identity_rows")
            return dict(result or {})
        return {"scanned": 0, "updated": 0, "user_ptrs": [], "cleaned": 0, "cleaned_user_ptrs": []}

    def repair_vehicle_number_u(self) -> dict[str, Any]:
        if settings.gate_real_integration_enabled:
            result = self._run_bridge("repair_vehicle_number_u")
            return dict(result or {})
        return {"scanned": 0, "updated": 0, "user_ptrs": []}

    def repair_vehicle_visual_numbers(self, limit: int = 50) -> dict[str, Any]:
        safe_limit = max(0, int(limit))
        if settings.gate_real_integration_enabled:
            result = self._run_bridge("repair_vehicle_visual_numbers", {"limit": safe_limit})
            return dict(result or {})
        return {"scanned": 0, "updated": 0, "failed": 0, "user_ptrs": [], "failures": []}

    def get_key_permissions(self, key_external_id: str) -> list[dict[str, Any]]:
        if settings.gate_real_integration_enabled:
            result = self._run_bridge("get_key_permissions", {"external_key_id": key_external_id})
            return [dict(item) for item in result]
        return []

    def open_access_point(self, access_point_id: int, key_external_id: str | None = None) -> GateOpenResult:
        if settings.gate_real_integration_enabled:
            response = self._run_bridge(
                "open_access_point",
                {
                    "access_point_id": access_point_id,
                    "external_key_id": key_external_id,
                },
            )
            return GateOpenResult(
                success=bool(response.get("success")),
                message=str(response.get("message", "")),
                code=str(response.get("error_code")) if response.get("error_code") else None,
                details=dict(response.get("details") or {}) or None,
            )

        if settings.gate_open_mode == "simulate":
            is_success = random.random() <= settings.gate_open_success_rate
            if is_success:
                return GateOpenResult(success=True, message=f"Access point {access_point_id} is opening")
            return GateOpenResult(
                success=False,
                code="integration_unavailable",
                message="Failed to execute open command",
            )

        return GateOpenResult(
            success=False,
            code="integration_unavailable",
            message="Open action is not implemented",
        )

    @staticmethod
    def now_unix_ms() -> int:
        return int(datetime.now(timezone.utc).timestamp() * 1000)


gate_client = GateClient()
