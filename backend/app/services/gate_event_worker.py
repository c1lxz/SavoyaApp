from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from ..config import get_settings
from ..database import SessionLocal
from .access import process_courier_gate_entry_events
from .gate import gate_client
from .requests import delete_expired_requests

settings = get_settings()
logger = logging.getLogger(__name__)

# Maximum time (seconds) to defer sweeps while "Список пользователей" is open.
# After this threshold the sweep runs regardless — an indefinite deferral would
# prevent expired passes from ever being removed (e.g. if the window is stuck open
# after a failed gate_bridge UI operation).
_SWEEP_MAX_DEFER_SECONDS: float = 60.0
_sweep_defer_start: Optional[float] = None


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
    global _sweep_defer_start

    if not settings.gate_real_integration_enabled:
        return 0

    # Defer this cycle if "Список пользователей" is currently open: a removal burst can hold
    # GateTerm's UI for 20-30s+ per key, during which a staff member's manual "Добавить" click
    # has no search-probe protection (that workaround only covers the app-driven create path)
    # and depends entirely on gateterm_users_guard.py priming the window first.
    #
    # IMPORTANT: deferral is time-limited. If the window stays open beyond
    # _SWEEP_MAX_DEFER_SECONDS (e.g. it was left open after a failed gate_bridge operation),
    # the sweep runs anyway — an indefinite deferral would prevent expired passes from
    # ever being cleaned up, which is worse than any UI race risk.
    window_open = await asyncio.to_thread(gate_client.is_users_window_open)
    if window_open:
        now = time.monotonic()
        if _sweep_defer_start is None:
            _sweep_defer_start = now
        elapsed = now - _sweep_defer_start
        if elapsed < _SWEEP_MAX_DEFER_SECONDS:
            return 0  # Window open and within deferral limit — skip this cycle
        # Window has been open longer than the limit — run sweep anyway, then restart the
        # clock so the next 60-second deferral window begins fresh (not firing every cycle).
        logger.warning(
            "sweep_expired_requests_once: 'Список пользователей' open for %.0fs (> %.0fs limit) — "
            "running sweep anyway to prevent stale passes",
            elapsed,
            _SWEEP_MAX_DEFER_SECONDS,
        )
        _sweep_defer_start = time.monotonic()  # restart timer after forced sweep
    else:
        _sweep_defer_start = None  # Window closed — reset timer for next open event

    async with SessionLocal() as session:
        return await delete_expired_requests(session)


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
        # FIX: each operation has its own try/except so a failure in one
        # (e.g. get_recent_events ODBC error) never prevents the others from running.

        if maintenance_enabled:
            current_time = time.monotonic()
            if current_time >= next_maintenance_at:
                try:
                    await run_gate_maintenance_pass_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Failed to run Gate maintenance pass")
                finally:
                    next_maintenance_at = time.monotonic() + maintenance_interval

        try:
            scheduled_count = await poll_courier_gate_entry_events_once()
            if scheduled_count:
                logger.info("Scheduled %s courier request(s) for cleanup from Gate entry events", scheduled_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to poll Gate courier entry events")

        # Critical: always sweep expired passes — independent of poll result above.
        try:
            removed_count = await sweep_expired_requests_once()
            if removed_count:
                logger.info("Removed %s expired request(s) from Gate after expiry", removed_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to sweep expired Gate requests")

        await asyncio.sleep(interval)
