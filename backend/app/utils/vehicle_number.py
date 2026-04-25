from __future__ import annotations

import re
from typing import Any

_VEHICLE_SEPARATOR_RE = re.compile(r"[\s-]+")
_LOOKALIKE_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "У": "Y",
        "Х": "X",
    }
)


def canonicalize_vehicle_letters(value: Any) -> str:
    if value is None:
        return ""
    return str(value).upper().translate(_LOOKALIKE_CYRILLIC_TO_LATIN)


def compact_vehicle_number(value: Any) -> str:
    return _VEHICLE_SEPARATOR_RE.sub("", canonicalize_vehicle_letters(value))
