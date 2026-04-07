from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./backend_test.db"
os.environ["GATE_OPEN_SUCCESS_RATE"] = "1.0"
os.environ["GATE_REAL_INTEGRATION_ENABLED"] = "False"
os.environ["DEBUG"] = "False"
os.environ["BOOTSTRAP_DEMO_USER"] = "True"

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.main import app


@pytest.fixture(scope="session", autouse=True)
def reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client
