from __future__ import annotations

import pytest

from backend.app.utils.vehicle_country import detect_vehicle_country


@pytest.mark.parametrize(
    ("plate", "expected"),
    [
        ("А123АА77", "Россия"),
        ("A123AA05", "Россия"),
        ("123ABC02", "Казахстан"),
        ("1234AB5", "Беларусь"),
        ("10-PO-749", "Азербайджан"),
        ("35 OL 278", "Армения"),
        ("001AB12", "Армения"),
        ("01 A123BC", "Узбекистан"),
        ("01 123 ABC", "Кыргызстан"),
        ("B1234BC", "Болгария"),
        ("AA1234II", "Украина"),
        ("CA1234AB", "Болгария / Украина"),
        ("B123ABC", "Румыния"),
        ("34ABC123", "Турция"),
        ("1234AB77", "Таджикистан"),
        ("MH12AB1234", "Индия"),
        ("1234BCD", "Испания"),
        ("123ABC", "Эстония"),
        ("AB123CD", "Европа"),
        ("ABC123", "Европа"),
        ("AB12345", "Европа"),
        ("M-AB 1234", "Европа"),
    ],
)
def test_detect_vehicle_country_supports_broad_europe_and_asia(plate: str, expected: str):
    assert detect_vehicle_country(plate) == expected


@pytest.mark.parametrize("plate", ["7ABC123", "B 1234 XYZ", ""])
def test_detect_vehicle_country_skips_unsupported_or_non_target_patterns(plate: str):
    assert detect_vehicle_country(plate) is None
