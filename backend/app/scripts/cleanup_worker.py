from __future__ import annotations

import asyncio
import logging
import os

from backend.app.database import SessionLocal
from backend.app.services.cleanup import run_cleanup

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def _run_once() -> None:
    async with SessionLocal() as session:
        changed = await run_cleanup(session)
        if changed:
            logger.info("Cleanup worker: updated %s expired requests", changed)


async def main() -> None:
    interval = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "60"))
    while True:
        try:
            await _run_once()
        except Exception:  # pragma: no cover - defensive runtime worker loop
            logger.exception("Cleanup worker failed")
        await asyncio.sleep(max(5, interval))


if __name__ == "__main__":
    asyncio.run(main())
