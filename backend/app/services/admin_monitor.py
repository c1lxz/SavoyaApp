from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AccessEventLog, AccessPoint, User
from ..schemas import AdminMonitorEventItem, AdminMonitorResponse
from ..utils.datetime import ensure_utc_datetime
from .gate import gate_client

_GATE_APP_MATCH_WINDOW_SECONDS = 120


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


def _compose_identity_label(
    *,
    raw_name: Any | None = None,
    full_name: Any | None = None,
    key_value: Any | None = None,
    include_key_value: bool = True,
) -> str | None:
    normalized_raw_name = _str_or_none(raw_name)
    if normalized_raw_name is not None:
        return normalized_raw_name

    normalized_full_name = _str_or_none(full_name)
    normalized_key_value = _str_or_none(key_value)
    if include_key_value and normalized_full_name and normalized_key_value:
        return f"{normalized_key_value}   {normalized_full_name}"
    if normalized_full_name:
        return normalized_full_name
    return normalized_key_value if include_key_value else None


def _anonymous_gate_identity_label(*, unit: Any | None = None, access_point_name: Any | None = None) -> str | None:
    labels = [unit, access_point_name]
    for label in labels:
        text = _str_or_none(label)
        if text is None:
            continue
        normalized = text.casefold()
        if "gsm" in normalized or "телефон" in normalized or "вызов" in normalized:
            return "Анонимный GSM"
    return None


def _gate_status(event_code: int | None) -> str:
    return "success" if event_code in {2, 8, 56, 208} else "event"


def _timestamp_or_none(value: datetime | None) -> float | None:
    if value is None:
        return None
    value = ensure_utc_datetime(value) or value
    try:
        return value.timestamp()
    except OSError:
        return None


def _match_app_context_for_gate_event(
    *,
    event_time: datetime,
    access_point_id: int | None,
    user_ptr: int | None,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if user_ptr is None:
        return None

    event_timestamp = _timestamp_or_none(event_time)
    if event_timestamp is None:
        return None

    matched: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        candidate_gate_key_id = _int_or_none(candidate.get("gate_key_id"))
        if candidate_gate_key_id != user_ptr:
            continue

        candidate_access_point_id = _int_or_none(candidate.get("access_point_id"))
        if (
            access_point_id is not None
            and candidate_access_point_id is not None
            and candidate_access_point_id != access_point_id
        ):
            continue

        candidate_timestamp = _timestamp_or_none(candidate.get("created_at"))
        if candidate_timestamp is None:
            continue

        distance = abs(event_timestamp - candidate_timestamp)
        if distance <= _GATE_APP_MATCH_WINDOW_SECONDS:
            matched.append((distance, candidate))

    if not matched:
        return None
    matched.sort(key=lambda item: item[0])
    return matched[0][1]


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
    app_context_candidates: list[dict[str, Any]] = []
    for event, user, point in query.all():
        details = event.details or {}
        observed = _observed_gate_event(details)
        observed_index = _int_or_none((observed or {}).get("index"))
        app_request_id = _int_or_none(details.get("request_db_id"))
        gate_key_id = _int_or_none(details.get("gate_key_id"))
        key_type = _str_or_none(details.get("key_type"))
        key_value = _str_or_none(details.get("key_value"))
        gate_name = _str_or_none((observed or {}).get("name"))
        actor_full_name = user.name or _str_or_none(details.get("actor_name"))
        actor_name = _compose_identity_label(
            full_name=actor_full_name,
            key_value=key_value,
            include_key_value=False,
        )
        actor_phone = user.phone or _str_or_none(details.get("actor_phone"))
        actor_login = user.login or _str_or_none(details.get("actor_login"))
        item = AdminMonitorEventItem(
            id=f"app-{event.id}",
            source="app",
            created_at=ensure_utc_datetime(event.created_at) or event.created_at,
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
        app_context = {
            "item_id": item.id,
            "event_id": event.id,
            "created_at": ensure_utc_datetime(event.created_at) or event.created_at,
            "status": event.status,
            "message": event.error_message if event.status == "failed" else None,
            "request_id": event.request_id,
            "actor_user_id": user.id,
            "actor_login": actor_login,
            "actor_name": actor_full_name,
            "actor_phone": actor_phone,
            "access_point_id": event.access_point_id,
            "access_point_name": item.access_point_name,
            "app_request_id": app_request_id,
            "gate_key_id": gate_key_id,
            "key_type": key_type,
            "key_value": key_value,
        }
        app_context_candidates.append(app_context)
        if observed_index is not None:
            app_context_by_gate_index[observed_index] = app_context

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
        if app_context is None:
            app_context = _match_app_context_for_gate_event(
                event_time=event_time,
                access_point_id=access_point_id,
                user_ptr=user_ptr,
                candidates=app_context_candidates,
            )
        raw_gate_name = _str_or_none(event.get("name"))
        raw_gate_full_name = _str_or_none(event.get("full_name"))
        raw_gate_key_type = _str_or_none(event.get("key_type"))
        raw_gate_key_value = _str_or_none(event.get("key_value"))
        inferred_gate_full_name = _str_or_none(event.get("inferred_full_name"))
        inferred_gate_key_type = _str_or_none(event.get("inferred_key_type"))
        inferred_gate_key_value = _str_or_none(event.get("inferred_key_value"))
        display_gate_full_name = raw_gate_full_name or inferred_gate_full_name
        display_gate_key_type = raw_gate_key_type or inferred_gate_key_type
        display_gate_key_value = raw_gate_key_value or inferred_gate_key_value
        gate_identity_label = _compose_identity_label(
            raw_name=raw_gate_name,
            full_name=display_gate_full_name,
            key_value=display_gate_key_value,
        )
        if gate_identity_label is None:
            gate_identity_label = _anonymous_gate_identity_label(
                unit=event.get("unit"),
                access_point_name=app_context.get("access_point_name") if app_context is not None else None,
            )
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
                actor_name=(
                    _compose_identity_label(
                        full_name=app_context.get("actor_name"),
                        key_value=app_context.get("key_value"),
                        include_key_value=False,
                    )
                    if app_context is not None
                    else gate_identity_label
                ),
                actor_phone=_str_or_none(app_context.get("actor_phone")) if app_context is not None else None,
                access_point_id=_int_or_none(app_context.get("access_point_id")) if app_context is not None else access_point_id,
                access_point_name=(
                    _str_or_none(app_context.get("access_point_name"))
                    if app_context is not None
                    else _str_or_none(event.get("unit"))
                ),
                key_type=_str_or_none(app_context.get("key_type")) if app_context is not None else display_gate_key_type,
                key_value=_str_or_none(app_context.get("key_value")) if app_context is not None else display_gate_key_value,
                request_id=_str_or_none(app_context.get("request_id")) if app_context is not None else None,
                app_request_id=_int_or_none(app_context.get("app_request_id")) if app_context is not None else None,
                gate_key_id=_int_or_none(app_context.get("gate_key_id")) if app_context is not None else None,
                gate_event_index=index,
                gate_event_code=event_code,
                gate_user_ptr=user_ptr,
                gate_name=gate_identity_label,
                gate_original_name=raw_gate_name,
                gate_unit=_str_or_none(event.get("unit")),
                details=raw_gate_details,
            )
        )

    items = gate_items + [item for item in app_items if item.id not in matched_app_item_ids]
    items.sort(key=_sort_key, reverse=True)
    return AdminMonitorResponse(total=len(items), items=items, gate_error=gate_error)
