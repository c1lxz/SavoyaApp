from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.app.database import SessionLocal
from backend.app.services.vehicle_camera_simulator import (
    VehicleCameraSimulationError,
    simulate_vehicle_camera_open,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open a barrier by vehicle number and optionally simulate a backend camera-recognition event."
    )
    parser.add_argument("--vehicle-number", required=True, help="Vehicle number to resolve in backend/Gate.")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--access-point-id", type=int, help="Exact Gate access point id to open.")
    target.add_argument(
        "--action",
        choices=["entry", "exit", "wicket_north", "wicket_lake", "wicket_admin", "wicket_forest"],
        help="Named action from GATE_ACTION_MAP_JSON. Defaults to entry.",
    )
    parser.add_argument(
        "--open-only",
        action="store_true",
        help="Skip backend camera-event simulation and only perform the physical open.",
    )
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with SessionLocal() as session:
        result = await simulate_vehicle_camera_open(
            session,
            vehicle_number=args.vehicle_number,
            access_point_id=args.access_point_id,
            action=args.action,
            simulate_camera_event=not args.open_only,
        )
        return result.as_dict()


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        result = asyncio.run(_run(args))
    except VehicleCameraSimulationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:  # pragma: no cover - exercised manually
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
