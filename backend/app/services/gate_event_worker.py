from __future__ import annotations

import asyncio
import logging

from ..config import get_settings
from ..database import SessionLocal
from .access import process_courier_gate_entry_events
from .gate import gate_client

settings = get_settings()
logger = logging.getLogger(__name__)


async def poll_courier_gate_entry_events_once() -> int:
    if not settings.gate_real_integration_enabled:
        return 0

    limit = max(1, min(int(settings.gate_event_poll_limit), 500))
    events = await asyncio.to_thread(gate_client.get_recent_events, limit)
    async with SessionLocal() as session:
        return await process_courier_gate_entry_events(session, events)


async def courier_gate_event_worker() -> None:
    interval = max(5.0, float(settings.gate_event_poll_interval_seconds))
    while True:
        try:
            scheduled_count = await poll_courier_gate_entry_events_once()
            if scheduled_count:
                logger.info("Scheduled %s courier request(s) for cleanup from Gate entry events", scheduled_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to process Gate entry events")

        await asyncio.sleep(interval)
