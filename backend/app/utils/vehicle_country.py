from __future__ import annotations

import re

_MULTISPACE_RE = re.compile(r"\s+")
_SEPARATOR_RE = re.compile(r"[\s-]+")
_RUSSIAN_PLATE_RE = re.compile(r"^[ABEKMHOPCTYX]\d{3}[ABEKMHOPCTYX]{2}\d{2,3}$")
_KAZAKHSTAN_PLATE_RE = re.compile(r"^\d{3}[A-Z]{3}\d{2}$")
_BELARUS_PLATE_RE = re.compile(r"^\d{4}[A-Z]{2}\d$")
_AZERBAIJAN_PLATE_RE = re.compile(r"^\d{2}[A-Z]{2}\d{3}$")
_ARMENIA_GOVERNMENT_RE = re.compile(r"^\d{3}[A-Z]{2}\d{2}$")
_UZBEKISTAN_PLATE_RE = re.compile(r"^\d{2}[A-Z]\d{3}[A-Z]{2}$")
_KYRGYZSTAN_CURRENT_RE = re.compile(r"^\d{5}[A-Z]{3}$")
_TAJIKISTAN_PLATE_RE = re.compile(r"^\d{4}[A-Z]{2}\d{2}$")
_TURKEY_SINGLE_LETTER_RE = re.compile(r"^(0[1-9]|[1-7]\d|81)[A-Z]\d{4,5}$")
_TURKEY_DOUBLE_LETTER_RE = re.compile(r"^(0[1-9]|[1-7]\d|81)[A-Z]{2}\d{3,4}$")
_TURKEY_TRIPLE_LETTER_RE = re.compile(r"^(0[1-9]|[1-7]\d|81)[A-Z]{3}\d{2,3}$")
_ROMANIA_PLATE_RE = re.compile(r"^(?:B\d{2,3}[A-Z]{3}|[A-Z]{2}\d{2,3}[A-Z]{3})$")
_BG_UA_PLATE_RE = re.compile(r"^(?P<prefix>[A-Z]{1,2})\d{4}(?P<suffix>[A-Z]{2})$")
_INDIA_BHARAT_RE = re.compile(r"^BH\d{2}[A-Z]{1,2}\d{4}$")
_INDIA_STANDARD_RE = re.compile(r"^(?P<state>[A-Z]{2})\d{1,2}[A-Z]{1,3}\d{1,4}$")
_SERBIA_RAW_RE = re.compile(r"^[A-Z]{2}[- ]\d{3,4}[- ][A-Z]{2}$")
_GERMANIC_RAW_RE = re.compile(r"^[A-Z]{1,3}[- ][A-Z]{1,2}[- ]?\d{1,4}[A-Z]?$")
_EUROPE_TWO_THREE_TWO_RE = re.compile(r"^[A-Z]{2}\d{3}[A-Z]{2}$")
_SPAIN_PLATE_RE = re.compile(r"^\d{4}[A-Z]{3}$")
_SWEDEN_PLATE_RE = re.compile(r"^[A-Z]{3}\d{2}[A-Z]$")
_ESTONIA_PLATE_RE = re.compile(r"^\d{3}[A-Z]{3}$")
_EUROPE_THREE_THREE_RE = re.compile(r"^[A-Z]{3}\d{3}$")
_EUROPE_TWO_FIVE_RE = re.compile(r"^[A-Z]{2}\d{5}$")
_EUROPE_TWO_FOUR_RE = re.compile(r"^[A-Z]{2}\d{4}$")

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

_BULGARIA_REGION_CODES = {
    "A",
    "B",
    "BH",
    "BP",
    "BT",
    "C",
    "CA",
    "CB",
    "CC",
    "CH",
    "CM",
    "CO",
    "CT",
    "E",
    "EB",
    "EH",
    "EA",
    "H",
    "K",
    "KH",
    "M",
    "OB",
    "P",
    "PA",
    "PB",
    "PK",
    "PP",
    "T",
    "TX",
    "X",
    "Y",
}

_UKRAINE_REGION_CODES = {
    "AA",
    "AB",
    "AC",
    "AE",
    "AH",
    "AI",
    "AK",
    "AM",
    "AO",
    "AP",
    "AT",
    "AX",
    "BA",
    "BB",
    "BC",
    "BE",
    "BH",
    "BI",
    "BK",
    "BM",
    "BO",
    "BT",
    "BX",
    "CA",
    "CB",
    "CE",
    "CH",
    "CI",
    "CK",
    "CM",
    "CO",
    "CT",
    "CX",
    "EA",
    "HA",
    "HB",
    "HC",
    "HE",
    "HH",
    "HI",
    "HK",
    "HM",
    "HO",
    "HT",
    "HX",
    "IA",
    "KA",
    "KB",
    "KC",
    "KE",
    "KH",
    "KI",
    "KK",
    "KM",
    "KO",
    "KT",
    "KX",
}

_ROMANIA_COUNTY_CODES = {
    "AB",
    "AG",
    "AR",
    "B",
    "BC",
    "BH",
    "BN",
    "BR",
    "BT",
    "BV",
    "BZ",
    "CJ",
    "CL",
    "CS",
    "CT",
    "CV",
    "DB",
    "DJ",
    "GJ",
    "GL",
    "GR",
    "HD",
    "HR",
    "IF",
    "IL",
    "IS",
    "MH",
    "MM",
    "MS",
    "NT",
    "OT",
    "PH",
    "SB",
    "SJ",
    "SM",
    "SV",
    "TL",
    "TM",
    "TR",
    "VL",
    "VN",
    "VS",
}

_INDIA_STATE_CODES = {
    "AN",
    "AP",
    "AR",
    "AS",
    "BR",
    "CG",
    "CH",
    "DD",
    "DL",
    "DN",
    "GA",
    "GJ",
    "HP",
    "HR",
    "JH",
    "JK",
    "KA",
    "KL",
    "LA",
    "LD",
    "MH",
    "ML",
    "MN",
    "MP",
    "MZ",
    "NL",
    "OD",
    "PB",
    "PY",
    "RJ",
    "SK",
    "TN",
    "TR",
    "TS",
    "UK",
    "UP",
    "WB",
}


def _normalize_plate(value: str) -> tuple[str, str]:
    raw = _MULTISPACE_RE.sub(" ", value.strip().upper()).translate(_LOOKALIKE_CYRILLIC_TO_LATIN)
    compact = _SEPARATOR_RE.sub("", raw)
    return raw, compact


def _looks_like_azerbaijan(raw: str, compact: str) -> bool:
    return bool(_AZERBAIJAN_PLATE_RE.fullmatch(compact) and ("-" in raw or " " not in raw))


def _looks_like_armenia(raw: str, compact: str) -> bool:
    if _ARMENIA_GOVERNMENT_RE.fullmatch(compact):
        return True
    return bool(_AZERBAIJAN_PLATE_RE.fullmatch(compact) and " " in raw and "-" not in raw)


def _looks_like_turkey(compact: str) -> bool:
    return bool(
        _TURKEY_SINGLE_LETTER_RE.fullmatch(compact)
        or _TURKEY_DOUBLE_LETTER_RE.fullmatch(compact)
        or _TURKEY_TRIPLE_LETTER_RE.fullmatch(compact)
    )


def _detect_bulgaria_or_ukraine(compact: str) -> str | None:
    match = _BG_UA_PLATE_RE.fullmatch(compact)
    if match is None:
        return None

    prefix = match.group("prefix")
    is_bulgaria = prefix in _BULGARIA_REGION_CODES
    is_ukraine = prefix in _UKRAINE_REGION_CODES
    if is_bulgaria and not is_ukraine:
        return "Болгария"
    if is_ukraine and not is_bulgaria:
        return "Украина"
    if is_bulgaria and is_ukraine:
        return "Болгария / Украина"
    return None


def _looks_like_romania(compact: str) -> bool:
    if not _ROMANIA_PLATE_RE.fullmatch(compact):
        return False

    if compact.startswith("B") and len(compact) >= 3 and compact[1].isdigit():
        prefix = "B"
    else:
        prefix = compact[:2]
    return prefix in _ROMANIA_COUNTY_CODES


def _looks_like_india(compact: str) -> bool:
    if _INDIA_BHARAT_RE.fullmatch(compact):
        return True

    match = _INDIA_STANDARD_RE.fullmatch(compact)
    if match is None:
        return False
    return match.group("state") in _INDIA_STATE_CODES


def _looks_like_europe(raw: str, compact: str) -> bool:
    return bool(
        _GERMANIC_RAW_RE.fullmatch(raw)
        or _EUROPE_TWO_THREE_TWO_RE.fullmatch(compact)
        or _EUROPE_THREE_THREE_RE.fullmatch(compact)
        or _EUROPE_TWO_FIVE_RE.fullmatch(compact)
        or _EUROPE_TWO_FOUR_RE.fullmatch(compact)
    )


def detect_vehicle_country(value: str | None) -> str | None:
    if value is None:
        return None

    raw, compact = _normalize_plate(value)
    if not compact:
        return None

    if _RUSSIAN_PLATE_RE.fullmatch(compact):
        return "Россия"
    if _KAZAKHSTAN_PLATE_RE.fullmatch(compact):
        return "Казахстан"
    if _BELARUS_PLATE_RE.fullmatch(compact):
        return "Беларусь"
    if _UZBEKISTAN_PLATE_RE.fullmatch(compact):
        return "Узбекистан"
    if _KYRGYZSTAN_CURRENT_RE.fullmatch(compact):
        return "Кыргызстан"
    if _TAJIKISTAN_PLATE_RE.fullmatch(compact):
        return "Таджикистан"
    if _looks_like_romania(compact):
        return "Румыния"

    bulgaria_or_ukraine = _detect_bulgaria_or_ukraine(compact)
    if bulgaria_or_ukraine is not None:
        return bulgaria_or_ukraine

    if _SERBIA_RAW_RE.fullmatch(raw):
        return "Сербия"
    if _looks_like_azerbaijan(raw, compact):
        return "Азербайджан"
    if _looks_like_armenia(raw, compact):
        return "Армения"
    if _looks_like_turkey(compact):
        return "Турция"
    if _looks_like_india(compact):
        return "Индия"
    if _SPAIN_PLATE_RE.fullmatch(compact):
        return "Испания"
    if _SWEDEN_PLATE_RE.fullmatch(compact):
        return "Швеция"
    if _ESTONIA_PLATE_RE.fullmatch(compact):
        return "Эстония"
    if _looks_like_europe(raw, compact):
        return "Европа"
    return None
