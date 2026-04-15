from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AccessEventLog, AccessPoint, User
from ..schemas import AdminMonitorEventItem, AdminMonitorResponse
from .gate import gate_client


def _parse_gate_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.now()
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now()


def _sort_key(item: AdminMonitorEventItem) -> float:
    value = item.created_at
    try:
        return value.timestamp()
    except OSError:
        return 0


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _observed_gate_event(details: dict | None) -> dict | None:
    gate_result = (details or {}).get("gate_result")
    if not isinstance(gate_result, dict):
        return None
    observed = gate_result.get("observed_event")
    return observed if isinstance(observed, dict) else None


async def list_admin_monitor_events(session: AsyncSession, *, limit: int = 100) -> AdminMonitorResponse:
    safe_limit = max(1, min(int(limit), 500))
    query = await session.execute(
        select(AccessEventLog, User, AccessPoint)
        .join(User, User.id == AccessEventLog.user_id)
        .outerjoin(AccessPoint, AccessPoint.id == AccessEventLog.access_point_id)
        .order_by(AccessEventLog.created_at.desc(), AccessEventLog.id.desc())
        .limit(safe_limit)
    )

    items: list[AdminMonitorEventItem] = []
    for event, user, point in query.all():
        details = event.details or {}
        observed = _observed_gate_event(details)
        app_request_id = _int_or_none(details.get("request_db_id"))
        gate_key_id = _int_or_none(details.get("gate_key_id"))
        items.append(
            AdminMonitorEventItem(
                id=f"app-{event.id}",
                source="app",
                created_at=event.created_at,
                status=event.status,
                action=event.action,
                message=event.error_message if event.status == "failed" else "Команда открытия обработана приложением",
                actor_user_id=user.id,
                actor_login=user.login,
                actor_name=user.name,
                actor_phone=user.phone,
                access_point_id=event.access_point_id,
                access_point_name=point.name if point is not None else None,
                request_id=event.request_id,
                app_request_id=app_request_id,
                gate_key_id=gate_key_id,
                gate_event_index=_int_or_none((observed or {}).get("index")),
                gate_event_code=_int_or_none((observed or {}).get("event_code")),
                gate_user_ptr=gate_key_id,
                gate_name=str((observed or {}).get("name") or "") or None,
                gate_unit=str((observed or {}).get("unit") or "") or None,
                details=details,
            )
        )

    gate_error: str | None = None
    try:
        gate_events = gate_client.get_recent_events(safe_limit)
    except Exception as exc:
        gate_events = []
        gate_error = str(exc)

    for event in gate_events:
        event_time = _parse_gate_time(event.get("time"))
        index = _int_or_none(event.get("index"))
        access_point_id = _int_or_none(event.get("access_point_id"))
        user_ptr = _int_or_none(event.get("user_ptr"))
        items.append(
            AdminMonitorEventItem(
                id=f"gate-{index if index is not None else len(items)}",
                source="gate",
                created_at=event_time,
                status="success" if _int_or_none(event.get("event_code")) in {2, 8, 56, 208} else "event",
                action="gate_event",
                message=str(event.get("message") or ""),
                access_point_id=access_point_id,
                access_point_name=str(event.get("unit") or "") or None,
                gate_event_index=index,
                gate_event_code=_int_or_none(event.get("event_code")),
                gate_user_ptr=user_ptr,
                gate_name=str(event.get("name") or "") or None,
                gate_unit=str(event.get("unit") or "") or None,
                details=event,
            )
        )

    items.sort(key=_sort_key, reverse=True)
    return AdminMonitorResponse(total=len(items), items=items, gate_error=gate_error)
