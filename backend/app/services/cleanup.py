from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .requests import cleanup_expired_requests

logger = logging.getLogger(__name__)


async def run_cleanup(session: AsyncSession) -> int:
    changed = await cleanup_expired_requests(session)
    if changed:
        logger.info("Expired requests cleanup updated %s rows", changed)
    return changed

