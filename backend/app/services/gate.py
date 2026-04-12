from __future__ import annotations

import json
import random
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings

settings = get_settings()
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_GATE_BRIDGE_SCRIPT = _PROJECT_ROOT / "backend" / "app" / "scripts" / "gate_bridge.py"


@dataclass
class GateOpenResult:
    success: bool
    message: str
    code: str | None = None
    details: dict[str, Any] | None = None


class GateClient:
    def __init__(self) -> None:
        self._fallback_counter = 10_000

    def _next_fallback_key_id(self) -> int:
        self._fallback_counter += 1
        return self._fallback_counter

    def _run_bridge(self, action: str, payload: dict[str, Any] | None = None) -> Any:
        command = [settings.gate_python_launcher]
        if settings.gate_python_version:
            command.append(settings.gate_python_version)
        command.extend([str(_GATE_BRIDGE_SCRIPT), action, json.dumps(payload or {}, ensure_ascii=False)])

        completed = subprocess.run(
            command,
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=settings.gate_bridge_timeout_seconds,
            check=False,
        )
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            message = stdout or stderr or f"Gate bridge failed with exit code {completed.returncode}"
            raise RuntimeError(message)

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Gate bridge returned invalid JSON: {stdout}") from exc

        if not data.get("ok"):
            raise RuntimeError(str(data.get("error") or "Gate bridge failed"))
        return data.get("result")

    def add_temporary_key(
        self,
        key_type: str,
        key_value: str,
        phone_number: str | None,
        expires_at: datetime,
        access_point_ids: list[int],
        resident_name: str,
    ) -> int:
        if settings.gate_real_integration_enabled:
            result = self._run_bridge(
                "add_temporary_key",
                {
                    "key_type": key_type,
                    "key_value": key_value,
                    "phone_number": phone_number,
                    "expires_at": expires_at.isoformat(),
                    "access_point_ids": access_point_ids,
                    "resident_name": resident_name,
                },
            )
            return int(result)
        return self._next_fallback_key_id()

    def add_permanent_key(
        self,
        key_type: str,
        key_value: str,
        phone_number: str | None,
        access_point_ids: list[int],
        resident_name: str,
    ) -> int:
        if settings.gate_real_integration_enabled:
            result = self._run_bridge(
                "add_permanent_key",
                {
                    "key_type": key_type,
                    "key_value": key_value,
                    "phone_number": phone_number,
                    "access_point_ids": access_point_ids,
                    "resident_name": resident_name,
                },
            )
            return int(result)
        return self._next_fallback_key_id()

    def remove_key(self, key_id: int) -> bool:
        if settings.gate_real_integration_enabled:
            return bool(self._run_bridge("remove_key", {"key_id": key_id}))
        return True

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
