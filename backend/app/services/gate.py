from __future__ import annotations

import importlib
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings

settings = get_settings()


def _load_gate_db_module():
    return importlib.import_module("gate_db")


@dataclass
class GateOpenResult:
    success: bool
    message: str
    code: str | None = None


class GateClient:
    def __init__(self) -> None:
        self._fallback_counter = 10_000

    def _next_fallback_key_id(self) -> int:
        self._fallback_counter += 1
        return self._fallback_counter

    def add_temporary_key(self, key_type: str, key_value: str, expires_at: datetime, access_point_ids: list[int]) -> int:
        if settings.gate_real_integration_enabled:
            module = _load_gate_db_module()
            return int(module.add_temporary_key(key_type, key_value, expires_at, access_point_ids))
        return self._next_fallback_key_id()

    def add_permanent_key(
        self,
        key_type: str,
        key_value: str,
        access_point_ids: list[int],
        resident_name: str,
    ) -> int:
        if settings.gate_real_integration_enabled:
            module = _load_gate_db_module()
            return int(module.add_permanent_key(key_type, key_value, access_point_ids, resident_name))
        return self._next_fallback_key_id()

    def remove_key(self, key_id: int) -> bool:
        if settings.gate_real_integration_enabled:
            module = _load_gate_db_module()
            return bool(module.remove_key(key_id))
        return True

    def get_access_points(self) -> list[dict[str, Any]]:
        if settings.gate_real_integration_enabled:
            module = _load_gate_db_module()
            return list(module.get_access_points())

        action_map = settings.gate_action_map
        reverse_map = {value: key for key, value in action_map.items()}
        points = []
        for point_id in sorted(reverse_map):
            points.append({"id": point_id, "name": reverse_map[point_id]})
        return points

    def open_access_point(self, access_point_id: int, key_external_id: str | None = None) -> GateOpenResult:
        if settings.gate_real_integration_enabled:
            module = _load_gate_db_module()
            if not hasattr(module, "open_access_point"):
                return GateOpenResult(
                    success=False,
                    code="integration_unavailable",
                    message="GATE open command is not implemented in gate_db.py",
                )

            response = module.open_access_point(access_point_id=access_point_id, external_key_id=key_external_id)
            return GateOpenResult(
                success=bool(response.get("success")),
                message=str(response.get("message", "")),
                code=str(response.get("error_code")) if response.get("error_code") else None,
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
