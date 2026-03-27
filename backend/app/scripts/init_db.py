from __future__ import annotations

import asyncio

from backend.app.database import Base, SessionLocal, engine
from backend.app.services.auth import ensure_demo_user

# Ensure SQLAlchemy model metadata is registered before create_all.
from backend.app import models as _models  # noqa: F401


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        await ensure_demo_user(session)


if __name__ == "__main__":
    asyncio.run(main())
