from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..models import Request
from ..utils.datetime import utcnow
from .access import process_courier_gate_entry_events
from .gate import gate_client
from .requests import delete_request_for_admin

settings = get_settings()
logger = logging.getLogger(__name__)


async def poll_courier_gate_entry_events_once() -> int:
    if not settings.gate_real_integration_enabled:
        return 0

    limit = max(1, min(int(settings.gate_event_poll_limit), 500))
    events = await asyncio.to_thread(gate_client.get_recent_events, limit)
    async with SessionLocal() as session:
        return await process_courier_gate_entry_events(session, events)


async def sweep_expired_requests_once() -> int:
    """Delete temporary passes whose expiry has elapsed — Gate key and app row alike.

    Courier passes have their expiry reset to ``entry_time + courier_default_hours``
    when the entry barrier opens (see ``process_courier_gate_entry_event``).  Once that
    window passes the pass must be *removed* from the Gate, not merely flagged
    "expired", using the same path as a manual admin deletion
    (``delete_request_for_admin``).  Rows already marked "expired" (e.g. by the startup
    cleanup, which does not touch the Gate) are picked up here too, so a Gate key can
    no longer linger after the app already considers the pass gone.
    """
    if not settings.gate_real_integration_enabled:
        return 0

    async with SessionLocal() as session:
        now = utcnow()
        query = await session.execute(
            select(Request.id).where(
                Request.is_permanent.is_(False),
                Request.expires_at.is_not(None),
                Request.expires_at <= now,
                Request.status.in_(("active", "expired")),
            )
        )
        expired_ids = [int(request_id) for request_id in query.scalars().all()]

    deleted = 0
    for request_id in expired_ids:
        try:
            async with SessionLocal() as session:
                if await delete_request_for_admin(session, request_id) is not None:
                    deleted += 1
        except Exception:
            logger.exception("Failed to delete expired request %s during sweep", request_id)
    return deleted


async def run_gate_maintenance_pass_once() -> None:
    try:
        phone_repair_result = await asyncio.to_thread(gate_client.repair_phone_identity_rows)
        updated = int(phone_repair_result.get("updated") or 0)
        cleaned = int(phone_repair_result.get("cleaned") or 0)
        if updated or cleaned:
            logger.info(
                "Gate maintenance repaired %s phone rows and cleaned %s conflicting rows",
                updated,
                cleaned,
            )
    except Exception:
        logger.exception("Failed to repair Gate phone identity rows during maintenance")

    try:
        vehicle_number_u_result = await asyncio.to_thread(gate_client.repair_vehicle_number_u)
        updated = int(vehicle_number_u_result.get("updated") or 0)
        if updated:
            logger.info("Gate maintenance repaired %s vehicle rows", updated)
    except Exception:
        logger.exception("Failed to repair Gate vehicle rows during maintenance")

    try:
        vehicle_visual_result = await asyncio.to_thread(gate_client.repair_vehicle_visual_numbers)
        updated = int(vehicle_visual_result.get("updated") or 0)
        failed = int(vehicle_visual_result.get("failed") or 0)
        if updated or failed:
            logger.info(
                "Gate maintenance post-synced %s vehicle visual rows with %s failures",
                updated,
                failed,
            )
    except Exception:
        logger.exception("Failed to repair Gate vehicle visual rows during maintenance")

    try:
        display_name_result = await asyncio.to_thread(gate_client.repair_user_display_names)
        updated = int(display_name_result.get("updated") or 0)
        if updated:
            logger.info("Gate maintenance repaired %s Gate user display names", updated)
    except Exception:
        logger.exception("Failed to repair Gate user display names during maintenance")


async def courier_gate_event_worker() -> None:
    interval = max(5.0, float(settings.gate_event_poll_interval_seconds))
    maintenance_enabled = bool(settings.gate_background_maintenance_enabled)
    maintenance_interval = max(interval, float(settings.gate_maintenance_interval_seconds))
    next_maintenance_at = 0.0
    while True:
        try:
            current_time = time.monotonic()
            if maintenance_enabled and current_time >= next_maintenance_at:
                await run_gate_maintenance_pass_once()
                next_maintenance_at = current_time + maintenance_interval
            scheduled_count = await poll_courier_gate_entry_events_once()
            if scheduled_count:
                logger.info("Scheduled %s courier request(s) for cleanup from Gate entry events", scheduled_count)
            removed_count = await sweep_expired_requests_once()
            if removed_count:
                logger.info("Removed %s expired request(s) from Gate after expiry", removed_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to process Gate entry events")

        await asyncio.sleep(interval)
