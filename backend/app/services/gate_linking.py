from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Request, User
from ..utils.input_safety import normalize_phone_key
from .gate import gate_client

logger = logging.getLogger(__name__)


@dataclass
class GatePhoneLinkResult:
    linked_request_ids: list[int] = field(default_factory=list)
    access_point_count: int = 0
    error: str | None = None

    @property
    def linked_count(self) -> int:
        return len(self.linked_request_ids)


def _permission_access_point_ids(permissions: list[dict]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for item in permissions:
        raw_id = item.get("access_point_id") if isinstance(item, dict) else None
        try:
            point_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if point_id <= 0 or point_id in seen:
            continue
        seen.add(point_id)
        ids.append(point_id)
    return ids


async def link_existing_gate_passes_by_phone(session: AsyncSession, user: User) -> GatePhoneLinkResult:
    """Attach existing Gate access found by the resident phone to a new app account.

    The bridge can resolve a Gate user by phone and return its reader permissions.
    We then create an app-owned permanent phone request so the existing access
    becomes visible and usable from the application without taking over another
    app user's active request.
    """

    if user.is_admin or not user.phone:
        return GatePhoneLinkResult()

    try:
        phone_key = normalize_phone_key(user.phone)
    except ValueError as exc:
        return GatePhoneLinkResult(error=str(exc))

    existing_query = await session.execute(
        select(Request).where(
            Request.key_type == "Phone",
            Request.key_value == phone_key,
            Request.status == "active",
        )
    )
    existing_requests = list(existing_query.scalars().all())
    owned_existing = [item for item in existing_requests if item.resident_id == user.id]
    if owned_existing:
        owned = owned_existing[0]
        return GatePhoneLinkResult(
            linked_request_ids=[int(owned.id)],
            access_point_count=len(list(owned.access_point_ids or [])),
        )
    if existing_requests:
        logger.info(
            "Skipped Gate phone auto-link for user_id=%s: active app request already exists for phone",
            user.id,
        )
        return GatePhoneLinkResult()

    try:
        permissions = gate_client.get_key_permissions(phone_key)
    except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
        logger.warning("Gate phone auto-link lookup failed for user_id=%s: %s", user.id, exc)
        return GatePhoneLinkResult(error=str(exc))

    access_point_ids = _permission_access_point_ids(permissions)
    if not access_point_ids:
        return GatePhoneLinkResult()

    try:
        gate_key_id = gate_client.add_permanent_key(
            key_type="Phone",
            key_value=phone_key,
            phone_number=phone_key,
            access_point_ids=access_point_ids,
            resident_name=user.name or user.login or "Resident",
            plot_number=user.plot_number or user.apartment,
        )
    except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
        logger.warning("Gate phone auto-link write failed for user_id=%s: %s", user.id, exc)
        return GatePhoneLinkResult(error=str(exc))

    if gate_key_id <= 0:
        message = f"Gate returned invalid key id: {gate_key_id}"
        logger.warning("Gate phone auto-link failed for user_id=%s: %s", user.id, message)
        return GatePhoneLinkResult(error=message)

    request = Request(
        resident_id=user.id,
        key_type="Phone",
        key_value=phone_key,
        gate_key_id=gate_key_id,
        access_point_ids=access_point_ids,
        is_permanent=True,
        is_courier=False,
        contact_phone=phone_key,
        expires_at=None,
        status="active",
        plot_number=user.plot_number or user.apartment,
    )
    user.gate_user_id = gate_key_id
    session.add(user)
    session.add(request)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.info("Skipped Gate phone auto-link for user_id=%s after duplicate request race", user.id)
        return GatePhoneLinkResult(error=str(exc))

    await session.refresh(request)
    return GatePhoneLinkResult(
        linked_request_ids=[int(request.id)],
        access_point_count=len(access_point_ids),
    )
