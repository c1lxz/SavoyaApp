from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Request, User
from ..utils.datetime import ensure_utc_datetime
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


async def _recover_gate_phone_key_id(*, phone_key: str, context: str) -> int | None:
    try:
        resolved_key_id = await asyncio.to_thread(gate_client.resolve_key_id, phone_key)
    except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
        logger.warning(
            "Gate phone key recovery failed for %s phone=%s: %s",
            context,
            phone_key,
            exc,
        )
        return None

    if resolved_key_id is None or int(resolved_key_id) <= 0:
        return None

    resolved_key_id = int(resolved_key_id)
    logger.warning(
        "Recovered Gate phone key_id=%s for %s phone=%s after UI provisioning error",
        resolved_key_id,
        context,
        phone_key,
    )
    return resolved_key_id


async def _resolve_gate_phone_key_id(*, phone_key: str, context: str) -> int | None:
    try:
        resolved_key_id = await asyncio.to_thread(gate_client.resolve_key_id, phone_key)
    except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
        logger.warning(
            "Gate phone key lookup failed for %s phone=%s: %s",
            context,
            phone_key,
            exc,
        )
        return None

    if resolved_key_id is None or int(resolved_key_id) <= 0:
        return None
    return int(resolved_key_id)


async def _provision_gate_phone_key(
    *,
    phone_key: str,
    phone_number: str,
    access_point_ids: list[int],
    resident_name: str,
    plot_number: str | None,
    recovery_context: str,
) -> int:
    try:
        gate_key_id = await asyncio.to_thread(
            gate_client.add_account_phone_key,
            key_value=phone_key,
            phone_number=phone_number,
            access_point_ids=access_point_ids,
            resident_name=resident_name,
            plot_number=plot_number,
        )
    except Exception:
        recovered_key_id = await _recover_gate_phone_key_id(phone_key=phone_key, context=recovery_context)
        if recovered_key_id is None:
            raise
        gate_key_id = recovered_key_id

    if gate_key_id <= 0:
        raise RuntimeError(f"Gate returned invalid key id: {gate_key_id}")
    return int(gate_key_id)


async def _upsert_gate_phone_access(user: User, request: Request, access_point_ids: list[int]) -> int:
    return await _provision_gate_phone_key(
        phone_key=request.key_value,
        phone_number=request.contact_phone or request.key_value,
        access_point_ids=access_point_ids,
        resident_name=user.name or user.login or "Resident",
        plot_number=request.plot_number or user.plot_number or user.apartment,
        recovery_context=f"request_id={request.id} user_id={user.id}",
    )


async def _link_existing_gate_vehicle_passes_by_phone(session: AsyncSession, user: User, phone_key: str) -> list[int]:
    try:
        vehicle_rows = await asyncio.to_thread(gate_client.list_vehicle_keys_by_phone, phone_key)
    except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
        logger.warning("Gate vehicle auto-link lookup failed for user_id=%s phone=%s: %s", user.id, phone_key, exc)
        return []

    linked_ids: list[int] = []
    for item in vehicle_rows:
        key_value = str(item.get("key_value") or "").strip()
        if not key_value:
            continue

        existing_query = await session.execute(
            select(Request.id).where(
                Request.key_type == "VehicleNumber",
                Request.key_value == key_value,
                Request.status == "active",
            )
        )
        if existing_query.scalar_one_or_none() is not None:
            continue

        try:
            gate_key_id = int(item.get("gate_key_id") or 0)
        except (TypeError, ValueError):
            gate_key_id = 0
        access_point_ids = _permission_access_point_ids(
            [{"access_point_id": point_id} for point_id in (item.get("access_point_ids") or [])]
        )
        if not access_point_ids:
            continue

        raw_expires_at = item.get("expires_at")
        expires_at = raw_expires_at
        if isinstance(raw_expires_at, str):
            try:
                expires_at = datetime.fromisoformat(raw_expires_at.replace("Z", "+00:00"))
            except ValueError:
                expires_at = None

        request = Request(
            resident_id=user.id,
            key_type="VehicleNumber",
            key_value=key_value,
            gate_key_id=gate_key_id if gate_key_id > 0 else None,
            access_point_ids=access_point_ids,
            is_permanent=bool(item.get("is_permanent", True)),
            is_courier=False,
            contact_phone=phone_key,
            expires_at=ensure_utc_datetime(expires_at),
            status="active",
            plot_number=user.plot_number or user.apartment,
        )
        session.add(request)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue
        linked_ids.append(int(request.id))

    return linked_ids


async def _link_existing_gate_keys_by_phone(session: AsyncSession, user: User, phone_key: str) -> list[int]:
    try:
        gate_rows = await asyncio.to_thread(gate_client.list_keys_by_phone, phone_key)
    except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
        logger.warning("Gate key auto-link lookup failed for user_id=%s phone=%s: %s", user.id, phone_key, exc)
        return []

    linked_ids: list[int] = []
    for item in gate_rows:
        key_type = str(item.get("key_type") or "").strip()
        if key_type not in {"Phone", "VehicleNumber"}:
            continue

        key_value = str(item.get("key_value") or "").strip()
        if not key_value:
            continue

        existing_query = await session.execute(
            select(Request.id).where(
                Request.key_type == key_type,
                Request.key_value == key_value,
                Request.status == "active",
            )
        )
        if existing_query.scalar_one_or_none() is not None:
            continue

        try:
            gate_key_id = int(item.get("gate_key_id") or 0)
        except (TypeError, ValueError):
            gate_key_id = 0

        access_point_ids = _permission_access_point_ids(
            [{"access_point_id": point_id} for point_id in (item.get("access_point_ids") or [])]
        )
        if key_type == "Phone":
            access_point_ids = _configured_phone_access_point_ids(access_point_ids)
        elif not access_point_ids:
            access_point_ids = list(settings.default_access_point_ids)
        if not access_point_ids:
            continue

        raw_expires_at = item.get("expires_at")
        expires_at = raw_expires_at
        if isinstance(raw_expires_at, str):
            try:
                expires_at = datetime.fromisoformat(raw_expires_at.replace("Z", "+00:00"))
            except ValueError:
                expires_at = None

        request = Request(
            resident_id=user.id,
            key_type=key_type,
            key_value=key_value,
            gate_key_id=gate_key_id if gate_key_id > 0 else None,
            access_point_ids=access_point_ids,
            is_permanent=bool(item.get("is_permanent", True)),
            is_courier=False,
            contact_phone=phone_key,
            expires_at=ensure_utc_datetime(expires_at),
            status="active",
            plot_number=user.plot_number or user.apartment,
        )
        if key_type == "Phone" and gate_key_id > 0:
            user.gate_user_id = gate_key_id
            session.add(user)
        session.add(request)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue
        linked_ids.append(int(request.id))

    return linked_ids


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
            gate_key_id = await _upsert_gate_phone_access(user, request, desired_ids)
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
    """Ensure a resident account has a permanent Gate GSM/phone pass.

    If Gate already knows this phone, reuse its existing reader permissions and
    expand them with the configured default/GSM points. If Gate does not have a
    phone pass yet, provision a new permanent pass with the configured points so
    caller-id events in Gate Terminal resolve to the resident account.
    """

    if user.is_admin or not user.phone or not settings.gate_real_integration_enabled:
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
                gate_key_id = await _upsert_gate_phone_access(user, owned, desired_access_point_ids)
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
        permissions = await asyncio.to_thread(gate_client.get_key_permissions, phone_key)
    except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
        logger.warning(
            "Gate phone auto-link lookup failed for user_id=%s; continuing with configured defaults: %s",
            user.id,
            exc,
        )
        permissions = []

    existing_access_point_ids = _permission_access_point_ids(permissions)
    access_point_ids = _configured_phone_access_point_ids(existing_access_point_ids)

    existing_gate_request_ids: list[int] = []
    try:
        existing_gate_request_ids = await _link_existing_gate_keys_by_phone(session, user, phone_key)
    except IntegrityError as exc:
        await session.rollback()
        logger.info("Skipped Gate key auto-link for user_id=%s after duplicate request race", user.id)
        return GatePhoneLinkResult(error=str(exc))

    linked_phone_request_id: int | None = None
    if existing_gate_request_ids:
        linked_phone_query = await session.execute(
            select(Request.id).where(
                Request.id.in_(existing_gate_request_ids),
                Request.key_type == "Phone",
                Request.status == "active",
            )
        )
        linked_phone_request_id = linked_phone_query.scalar_one_or_none()
        if linked_phone_request_id is not None:
            await session.commit()
            return GatePhoneLinkResult(
                linked_request_ids=existing_gate_request_ids,
                access_point_count=len(access_point_ids),
            )

    gate_key_id = await _resolve_gate_phone_key_id(phone_key=phone_key, context=f"user_id={user.id}")
    if gate_key_id is not None:
        if existing_access_point_ids:
            access_point_ids = existing_access_point_ids
    else:
        if existing_gate_request_ids:
            await session.commit()
            return GatePhoneLinkResult(
                linked_request_ids=existing_gate_request_ids,
                access_point_count=len(access_point_ids),
            )

        if not access_point_ids:
            return GatePhoneLinkResult()

        try:
            gate_key_id = await _provision_gate_phone_key(
                phone_key=phone_key,
                phone_number=phone_key,
                access_point_ids=access_point_ids,
                resident_name=user.name or user.login or "Resident",
                plot_number=user.plot_number or user.apartment,
                recovery_context=f"user_id={user.id}",
            )
        except Exception as exc:  # pragma: no cover - depends on local Gate bridge/runtime.
            logger.warning("Gate phone auto-link write failed for user_id=%s: %s", user.id, exc)
            return GatePhoneLinkResult(error=str(exc))

    if not access_point_ids:
        return GatePhoneLinkResult()

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
        vehicle_request_ids = await _link_existing_gate_vehicle_passes_by_phone(session, user, phone_key)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.info("Skipped Gate phone auto-link for user_id=%s after duplicate request race", user.id)
        return GatePhoneLinkResult(error=str(exc))

    await session.refresh(request)
    return GatePhoneLinkResult(
        linked_request_ids=[int(request.id), *vehicle_request_ids],
        access_point_count=len(access_point_ids),
    )


async def ensure_users_have_gate_phone_requests(session: AsyncSession) -> int:
    """Backfill permanent Gate phone requests for resident accounts missing them."""

    if not settings.gate_real_integration_enabled:
        return 0

    rows = await session.execute(
        select(User)
        .where(
            User.is_admin.is_(False),
            User.is_active.is_(True),
            User.phone.is_not(None),
        )
        .order_by(User.created_at.asc(), User.id.asc())
    )

    ensured = 0
    for user in rows.scalars().all():
        existing_query = await session.execute(
            select(Request.id).where(
                Request.resident_id == user.id,
                Request.key_type == "Phone",
                Request.status == "active",
            )
        )
        if existing_query.scalar_one_or_none() is not None:
            continue

        result = await link_existing_gate_passes_by_phone(session, user)
        if result.linked_count > 0:
            ensured += result.linked_count
            continue
        if result.error:
            logger.warning(
                "Failed to ensure Gate phone request for user_id=%s phone=%s: %s",
                user.id,
                user.phone,
                result.error,
            )

    return ensured
