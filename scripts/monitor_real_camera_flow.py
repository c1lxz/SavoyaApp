from __future__ import annotations

import argparse
import json
import time
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.scripts import gate_runtime
from backend.app.utils.input_safety import normalize_vehicle_number


CAMERA_ACCESS_POINT_IDS = {19, 20}
PASS_EVENT_CODES = {2, 8}
DENY_EVENT_CODES = {1}


def _event_index(event: dict[str, Any]) -> int:
    return int(event.get("index") or 0)


def _is_camera_event(event: dict[str, Any]) -> bool:
    unit = str(event.get("unit") or "")
    try:
        access_point_id = int(event.get("access_point_id") or 0)
    except (TypeError, ValueError):
        access_point_id = 0
    return access_point_id in CAMERA_ACCESS_POINT_IDS or "Камера" in unit


def _plate_from_event(event: dict[str, Any]) -> str:
    key_value = str(event.get("key_value") or "").strip()
    if key_value:
        return key_value
    return str(event.get("name") or "").strip().split("   ", 1)[0].strip()


def _fio_from_event(event: dict[str, Any]) -> str:
    full_name = str(event.get("full_name") or "").strip()
    if full_name:
        return full_name
    name = str(event.get("name") or "")
    if "   " in name:
        return name.split("   ", 1)[1].strip()
    return ""


def _status(event: dict[str, Any]) -> str:
    event_type = int(event.get("event_type") or 0)
    event_code = int(event.get("event_code") or 0)
    plate = _plate_from_event(event)
    fio = _fio_from_event(event)
    user_ptr = event.get("user_ptr")
    if event_type == 1 and event_code in PASS_EVENT_CODES:
        if plate and fio and user_ptr:
            return "PASS: allowed camera event has plate and FIO"
        return "FAIL: allowed camera event is missing plate/FIO/user"
    if event_type == 2 and event_code in DENY_EVENT_CODES:
        if plate and not user_ptr:
            return "PASS: denied unknown plate without opening"
        return "FAIL: denied camera event has invalid identity fields"
    return "INFO: camera event"


def _normalize_expected_plate(value: str) -> str:
    return normalize_vehicle_number(value).replace(" ", "")


def _render_markdown(events: list[dict[str, Any]], expected: list[str] | None = None) -> str:
    lines = [
        "| # | time | access_point | plate | FIO | event | status |",
        "|---:|---|---|---|---|---|---|",
    ]
    emitted_expected: set[str] = set()
    for event in sorted(events, key=_event_index):
        plate = _plate_from_event(event)
        normalized_plate = _normalize_expected_plate(plate) if plate else ""
        if expected and normalized_plate not in expected:
            continue
        if normalized_plate:
            emitted_expected.add(normalized_plate)
        lines.append(
            "| {index} | {time} | {unit} | {plate} | {fio} | {message} | {status} |".format(
                index=event.get("index", ""),
                time=event.get("time", ""),
                unit=str(event.get("unit") or "").replace("|", "\\|"),
                plate=plate.replace("|", "\\|"),
                fio=_fio_from_event(event).replace("|", "\\|"),
                message=str(event.get("message") or "").replace("|", "\\|"),
                status=_status(event).replace("|", "\\|"),
            )
        )
    for plate in expected or []:
        if plate in emitted_expected:
            continue
        lines.append(f"|  |  |  | {plate} |  | no camera event captured | FAIL: expected plate was not seen |")
    return "\n".join(lines)


def _collect(duration_seconds: int, poll_seconds: float) -> list[dict[str, Any]]:
    baseline = gate_runtime.get_recent_events(limit=1)
    baseline_index = max((_event_index(item) for item in baseline), default=0)
    deadline = time.monotonic() + duration_seconds
    found: dict[int, dict[str, Any]] = {}

    while time.monotonic() < deadline:
        for event in gate_runtime.get_recent_events(limit=100):
            index = _event_index(event)
            if index <= baseline_index or not _is_camera_event(event):
                continue
            found[index] = event
        time.sleep(poll_seconds)

    return [found[index] for index in sorted(found)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only monitor for real Gate camera events. Does not open gates or modify passes."
    )
    parser.add_argument("--duration", type=int, default=180, help="Monitoring duration in seconds.")
    parser.add_argument("--poll", type=float, default=2.0, help="Polling interval in seconds.")
    parser.add_argument("--out-dir", default="diagnostics", help="Directory for JSON and Markdown logs.")
    parser.add_argument(
        "--expected",
        nargs="*",
        default=None,
        help="Optional expected vehicle plates. Missing plates are reported as FAIL rows.",
    )
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) / f"real_camera_flow_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    expected = [_normalize_expected_plate(item) for item in args.expected or []]
    events = _collect(duration_seconds=max(1, args.duration), poll_seconds=max(0.5, args.poll))
    (out_dir / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    table = _render_markdown(events, expected=expected or None)
    (out_dir / "table.md").write_text(table + "\n", encoding="utf-8")

    print(f"events={len(events)}")
    print(f"json={out_dir / 'events.json'}")
    print(f"table={out_dir / 'table.md'}")
    if events or expected:
        print(table)
    if expected:
        seen = {_normalize_expected_plate(_plate_from_event(event)) for event in events if _plate_from_event(event)}
        return 0 if set(expected).issubset(seen) else 2
    return 0 if events else 2


if __name__ == "__main__":
    raise SystemExit(main())
