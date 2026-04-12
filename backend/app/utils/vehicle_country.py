from __future__ import annotations

import re

_RUSSIAN_PLATE_RE = re.compile(r"^[ABEKMHOPCTYXАВЕКМНОРСТУХ]\d{3}[ABEKMHOPCTYXАВЕКМНОРСТУХ]{2}\d{2,3}$")
_KAZAKHSTAN_PLATE_RE = re.compile(r"^\d{3}[A-ZА-Я]{3}\d{2}$")


def detect_vehicle_country(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = re.sub(r"[\s-]+", "", value.upper())
    if not normalized:
        return None

    if _RUSSIAN_PLATE_RE.fullmatch(normalized):
        return "Россия"
    if _KAZAKHSTAN_PLATE_RE.fullmatch(normalized):
        return "Казахстан"
    return None
