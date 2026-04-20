from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Request, User
from ..utils.input_safety import normalize_phone_key
from .gate import gate_client

logger = logging.getLogger(__name__)
settings = get_settings()


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


def _merge_access_point_ids(*groups: Iterable[int]) -> list[int]:
    merged: list[int] = []
    seen: set[int] = set()
    for group in groups:
        for item in group:
            point_id = int(item)
            if point_id <= 0 or point_id in seen:
                continue
            seen.add(point_id)
            merged.append(point_id)
    return merged


def _configured_phone_access_point_ids(existing_access_point_ids: Iterable[int]) -> list[int]:
    return _merge_access_point_ids(
        settings.default_access_point_ids,
        settings.gsm_access_point_ids,
        existing_access_point_ids,
    )


def _request_access_point_ids(request: Request) -> list[int]:
    return [int(point_id) for point_id in (request.access_point_ids or [])]


def _upsert_gate_phone_access(user: User, request: Request, access_point_ids: list[int]) -> int:
    gate_key_id = gate_client.add_permanent_key(
        key_type="Phone",
        key_value=request.key_value,
        phone_number=request.contact_phone or request.key_value,
        access_point_ids=access_point_ids,
        resident_name=user.name or user.login or "Resident",
        plot_number=request.plot_number or user.plot_number or user.apartment,
    )
    if gate_key_id <= 0:
        raise RuntimeError(f"Gate returned invalid key id: {gate_key_id}")
    return gate_key_id


async def ensure_existing_phone_requests_have_configured_access(session: AsyncSession) -> int:
    """Expand active permanent phone passes to the configured default and GSM points.

    Older auto-linked Gate phone passes could contain only their existing GSM
    reader permissions, which made app buttons fail for the regular barrier and
    wicket access points. Keep any extra existing permissions, but always prepend
    the configured default and GSM points in the same order as newly created
    phone passes.
    """

    configured_ids = _merge_access_point_ids(settings.default_access_point_ids, settings.gsm_access_point_ids)
    if not configured_ids:
        return 0

    rows = await session.execute(
        select(Request, User)
        .join(User, User.id == Request.resident_id)
        .where(
            Request.key_type == "Phone",
            Request.status == "active",
            Request.is_permanent.is_(True),
        )
    )

    changed = 0
    for request, user in rows.all():
        current_ids = _request_access_point_ids(request)
        desired_ids = _configured_phone_access_point_ids(current_ids)
        if desired_ids == current_ids:
            continue
        if request.gate_key_id is None:
            logger.warning(
                "Skipped Gate phone access expansion for request_id=%s: missing gate_key_id",
                request.id,
            )
            continue

        try:
            gate_key_id = _upsert_gate_phone_access(user, request, desired_ids)
        except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
            logger.warning(
                "Gate phone access expansion failed for request_id=%s user_id=%s: %s",
                request.id,
                user.id,
                exc,
            )
            continue

        request.gate_key_id = gate_key_id
        request.access_point_ids = desired_ids
        user.gate_user_id = gate_key_id
        session.add(user)
        session.add(request)
        changed += 1

    if changed:
        await session.commit()
    return changed


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
        access_point_ids = _request_access_point_ids(owned)
        desired_access_point_ids = (
            _configured_phone_access_point_ids(access_point_ids) if owned.is_permanent else access_point_ids
        )
        if owned.is_permanent and desired_access_point_ids != access_point_ids:
            try:
                gate_key_id = _upsert_gate_phone_access(user, owned, desired_access_point_ids)
            except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
                logger.warning("Gate phone auto-link refresh failed for user_id=%s: %s", user.id, exc)
                return GatePhoneLinkResult(error=str(exc))
            owned.gate_key_id = gate_key_id
            owned.access_point_ids = desired_access_point_ids
            user.gate_user_id = gate_key_id
            session.add(user)
            session.add(owned)
            await session.commit()
            await session.refresh(owned)
            access_point_ids = desired_access_point_ids
        return GatePhoneLinkResult(
            linked_request_ids=[int(owned.id)],
            access_point_count=len(access_point_ids),
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

    existing_access_point_ids = _permission_access_point_ids(permissions)
    if not existing_access_point_ids:
        return GatePhoneLinkResult()
    access_point_ids = _configured_phone_access_point_ids(existing_access_point_ids)

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
