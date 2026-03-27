from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.services.requests import resolve_request_status


def test_resolve_request_status_permanent():
    assert resolve_request_status(is_permanent=True, expires_at=None) == "permanent"


def test_resolve_request_status_expired():
    old_date = datetime.now(timezone.utc) - timedelta(days=1)
    assert resolve_request_status(is_permanent=False, expires_at=old_date) == "expired"


def test_resolve_request_status_active():
    future = datetime.now(timezone.utc) + timedelta(days=1)
    assert resolve_request_status(is_permanent=False, expires_at=future) == "active"

