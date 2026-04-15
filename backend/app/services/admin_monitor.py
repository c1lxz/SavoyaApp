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


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _gate_status(event_code: int | None) -> str:
    return "success" if event_code in {2, 8, 56, 208} else "event"


async def list_admin_monitor_events(session: AsyncSession, *, limit: int = 100) -> AdminMonitorResponse:
    safe_limit = max(1, min(int(limit), 500))
    query = await session.execute(
        select(AccessEventLog, User, AccessPoint)
        .join(User, User.id == AccessEventLog.user_id)
        .outerjoin(AccessPoint, AccessPoint.id == AccessEventLog.access_point_id)
        .order_by(AccessEventLog.created_at.desc(), AccessEventLog.id.desc())
        .limit(safe_limit)
    )

    app_items: list[AdminMonitorEventItem] = []
    app_context_by_gate_index: dict[int, dict[str, Any]] = {}
    for event, user, point in query.all():
        details = event.details or {}
        observed = _observed_gate_event(details)
        observed_index = _int_or_none((observed or {}).get("index"))
        app_request_id = _int_or_none(details.get("request_db_id"))
        gate_key_id = _int_or_none(details.get("gate_key_id"))
        key_type = _str_or_none(details.get("key_type"))
        key_value = _str_or_none(details.get("key_value"))
        gate_name = _str_or_none((observed or {}).get("name"))
        actor_name = user.name or _str_or_none(details.get("actor_name"))
        actor_phone = user.phone or _str_or_none(details.get("actor_phone"))
        actor_login = user.login or _str_or_none(details.get("actor_login"))
        item = AdminMonitorEventItem(
            id=f"app-{event.id}",
            source="app",
            created_at=event.created_at,
            status=event.status,
            action=event.action,
            message=event.error_message if event.status == "failed" else "Команда открытия обработана приложением",
            actor_user_id=user.id,
            actor_login=actor_login,
            actor_name=actor_name,
            actor_phone=actor_phone,
            access_point_id=event.access_point_id,
            access_point_name=point.name if point is not None else _str_or_none(details.get("access_point_name")),
            key_type=key_type,
            key_value=key_value,
            request_id=event.request_id,
            app_request_id=app_request_id,
            gate_key_id=gate_key_id,
            gate_event_index=observed_index,
            gate_event_code=_int_or_none((observed or {}).get("event_code")),
            gate_user_ptr=gate_key_id,
            gate_name=gate_name,
            gate_original_name=gate_name,
            gate_unit=_str_or_none((observed or {}).get("unit")),
            details=details,
        )
        app_items.append(item)
        if observed_index is not None:
            app_context_by_gate_index[observed_index] = {
                "item_id": item.id,
                "event_id": event.id,
                "created_at": event.created_at,
                "status": event.status,
                "message": event.error_message if event.status == "failed" else None,
                "request_id": event.request_id,
                "actor_user_id": user.id,
                "actor_login": actor_login,
                "actor_name": actor_name,
                "actor_phone": actor_phone,
                "access_point_id": event.access_point_id,
                "access_point_name": item.access_point_name,
                "app_request_id": app_request_id,
                "gate_key_id": gate_key_id,
                "key_type": key_type,
                "key_value": key_value,
            }

    gate_error: str | None = None
    try:
        gate_events = gate_client.get_recent_events(safe_limit)
    except Exception as exc:
        gate_events = []
        gate_error = str(exc)

    gate_items: list[AdminMonitorEventItem] = []
    matched_app_item_ids: set[str] = set()
    for event in gate_events:
        event_time = _parse_gate_time(event.get("time"))
        index = _int_or_none(event.get("index"))
        access_point_id = _int_or_none(event.get("access_point_id"))
        user_ptr = _int_or_none(event.get("user_ptr"))
        event_code = _int_or_none(event.get("event_code"))
        app_context = app_context_by_gate_index.get(index) if index is not None else None
        raw_gate_name = _str_or_none(event.get("name"))
        raw_gate_details = dict(event)
        if app_context is not None:
            matched_app_item_ids.add(str(app_context["item_id"]))
            raw_gate_details = {
                **raw_gate_details,
                "gate_original_name": raw_gate_name,
                "app_event": {
                    "event_id": app_context["event_id"],
                    "request_id": app_context["request_id"],
                    "actor_login": app_context["actor_login"],
                    "actor_name": app_context["actor_name"],
                    "actor_phone": app_context["actor_phone"],
                    "app_request_id": app_context["app_request_id"],
                    "gate_key_id": app_context["gate_key_id"],
                    "key_type": app_context["key_type"],
                    "key_value": app_context["key_value"],
                },
            }

        gate_items.append(
            AdminMonitorEventItem(
                id=f"gate-{index if index is not None else len(gate_items) + len(app_items)}",
                source="gate",
                created_at=event_time,
                status=str(app_context["status"]) if app_context is not None else _gate_status(event_code),
                action="open" if app_context is not None else "gate_event",
                message=(
                    str(app_context["message"])
                    if app_context is not None and app_context.get("message")
                    else "Открыто из приложения"
                    if app_context is not None
                    else str(event.get("message") or "")
                ),
                actor_user_id=_int_or_none(app_context.get("actor_user_id")) if app_context is not None else None,
                actor_login=_str_or_none(app_context.get("actor_login")) if app_context is not None else None,
                actor_name=_str_or_none(app_context.get("actor_name")) if app_context is not None else None,
                actor_phone=_str_or_none(app_context.get("actor_phone")) if app_context is not None else None,
                access_point_id=_int_or_none(app_context.get("access_point_id")) if app_context is not None else access_point_id,
                access_point_name=(
                    _str_or_none(app_context.get("access_point_name"))
                    if app_context is not None
                    else _str_or_none(event.get("unit"))
                ),
                key_type=_str_or_none(app_context.get("key_type")) if app_context is not None else None,
                key_value=_str_or_none(app_context.get("key_value")) if app_context is not None else None,
                request_id=_str_or_none(app_context.get("request_id")) if app_context is not None else None,
                app_request_id=_int_or_none(app_context.get("app_request_id")) if app_context is not None else None,
                gate_key_id=_int_or_none(app_context.get("gate_key_id")) if app_context is not None else None,
                gate_event_index=index,
                gate_event_code=event_code,
                gate_user_ptr=user_ptr,
                gate_name=raw_gate_name,
                gate_original_name=raw_gate_name,
                gate_unit=_str_or_none(event.get("unit")),
                details=raw_gate_details,
            )
        )

    items = gate_items + [item for item in app_items if item.id not in matched_app_item_ids]
    items.sort(key=_sort_key, reverse=True)
    return AdminMonitorResponse(total=len(items), items=items, gate_error=gate_error)
