from __future__ import annotations

import asyncio
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./backend_test.db"
os.environ["GATE_OPEN_SUCCESS_RATE"] = "1.0"
os.environ["GATE_REAL_INTEGRATION_ENABLED"] = "False"
os.environ["DEBUG"] = "False"
os.environ["BOOTSTRAP_DEMO_USER"] = "True"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import AccessEventLog, AccessKey, AccessPermission, Log, Request


@pytest.fixture(scope="session", autouse=True)
def reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_login_rate_limiter():
    limiter = app.state.login_rate_limiter
    limiter._events.clear()
    yield
    limiter._events.clear()


async def _reset_database_state() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(AccessEventLog))
        await session.execute(delete(AccessPermission))
        await session.execute(delete(AccessKey))
        await session.execute(delete(Log))
        await session.execute(delete(Request))
        await session.commit()


@pytest.fixture(autouse=True)
def reset_database_state():
    asyncio.run(_reset_database_state())
    yield
    asyncio.run(_reset_database_state())
