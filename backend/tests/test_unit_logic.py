from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.services.access import _normalize_access_point_type
from backend.app.services.requests import resolve_request_status
from backend.app.utils.input_safety import normalize_vehicle_number


def test_resolve_request_status_permanent():
    assert resolve_request_status(is_permanent=True, expires_at=None) == "permanent"


def test_resolve_request_status_expired():
    old_date = datetime.now(timezone.utc) - timedelta(days=1)
    assert resolve_request_status(is_permanent=False, expires_at=old_date) == "expired"


def test_resolve_request_status_active():
    future = datetime.now(timezone.utc) + timedelta(days=1)
    assert resolve_request_status(is_permanent=False, expires_at=future) == "active"


def test_resolve_request_status_accepts_naive_sqlite_datetime():
    future = (datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None)
    assert resolve_request_status(is_permanent=False, expires_at=future) == "active"


def test_normalize_access_point_type_detects_exit_barrier():
    assert _normalize_access_point_type("Камера Выезда") == "barrier_exit"


def test_normalize_access_point_type_detects_wicket_entry_variants():
    assert _normalize_access_point_type("Вход озеро") == "wicket"
    assert _normalize_access_point_type("Считыватель калитка 1") == "wicket"


def test_normalize_vehicle_number_converts_cyrillic_lookalikes_to_ascii():
    assert normalize_vehicle_number("а123сх 77") == "A123CX 77"


def test_normalize_vehicle_number_rejects_unsupported_cyrillic_letters():
    with pytest.raises(ValueError, match="vehicle_number contains unsupported characters"):
        normalize_vehicle_number("Ж123АА77")
