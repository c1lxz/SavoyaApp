from __future__ import annotations

import re
from typing import Any

_VEHICLE_SEPARATOR_RE = re.compile(r"[\s-]+")
_LOOKALIKE_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "\u0410": "A",
        "\u0412": "B",
        "\u0415": "E",
        "\u041a": "K",
        "\u041c": "M",
        "\u041d": "H",
        "\u041e": "O",
        "\u0420": "P",
        "\u0421": "C",
        "\u0422": "T",
        "\u0423": "Y",
        "\u0425": "X",
        "\u00c0": "A",
        "\u00c2": "B",
        "\u00c5": "E",
        "\u00ca": "K",
        "\u00cc": "M",
        "\u00cd": "H",
        "\u00ce": "O",
        "\u00d0": "P",
        "\u00d1": "C",
        "\u00d2": "T",
        "\u00d3": "Y",
        "\u00d5": "X",
    }
)
_PLATE_ALLOWED_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -")


def _repair_vehicle_mojibake(value: str) -> str:
    for encoding in ("cp1251", "latin-1"):
        try:
            repaired = value.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired:
            return repaired
    return value


def _candidate_score(value: str) -> tuple[int, int]:
    allowed_count = sum(1 for ch in value if ch in _PLATE_ALLOWED_CHARS)
    invalid_count = sum(1 for ch in value if ch not in _PLATE_ALLOWED_CHARS)
    return (allowed_count, -invalid_count)


def canonicalize_vehicle_letters(value: Any) -> str:
    if value is None:
        return ""
    raw_value = str(value)
    candidates = [raw_value]
    repaired_value = _repair_vehicle_mojibake(raw_value)
    if repaired_value != raw_value:
        candidates.append(repaired_value)

    normalized_candidates = [
        candidate.upper().translate(_LOOKALIKE_CYRILLIC_TO_LATIN)
        for candidate in candidates
    ]
    return max(normalized_candidates, key=_candidate_score)


def compact_vehicle_number(value: Any) -> str:
    return _VEHICLE_SEPARATOR_RE.sub("", canonicalize_vehicle_letters(value))
