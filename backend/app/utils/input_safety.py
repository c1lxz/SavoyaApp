from __future__ import annotations

import re

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_MULTISPACE_RE = re.compile(r"\s+")
_LOGIN_RE = re.compile(r"^[A-Za-z0-9_.@+-]{3,100}$")
_PLOT_RE = re.compile(r"^[A-Za-zА-Яа-я0-9/\- ]{1,20}$")
_VEHICLE_RE = re.compile(r"^[A-Za-zА-Яа-я0-9 \-]{3,20}$")


def normalize_plain_text(value: str, *, max_length: int, field_name: str) -> str:
    normalized = _MULTISPACE_RE.sub(" ", value.strip())
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} is too long")
    if "<" in normalized or ">" in normalized:
        raise ValueError(f"{field_name} must not contain HTML markup")
    if _CONTROL_CHARS_RE.search(normalized):
        raise ValueError(f"{field_name} must not contain control characters")
    return normalized


def normalize_login(value: str) -> str:
    normalized = normalize_plain_text(value, max_length=100, field_name="login")
    if not _LOGIN_RE.fullmatch(normalized):
        raise ValueError("login contains unsupported characters")
    return normalized


def normalize_password(value: str) -> str:
    if value is None:
        raise ValueError("password must not be empty")
    if len(value) > 128:
        raise ValueError("password is too long")
    if _CONTROL_CHARS_RE.search(value):
        raise ValueError("password must not contain control characters")
    if not value:
        raise ValueError("password must not be empty")
    return value


def normalize_strong_password(value: str) -> str:
    normalized = normalize_password(value)
    if len(normalized) < 10:
        raise ValueError("password must contain at least 10 characters")
    if not any(ch.islower() for ch in normalized):
        raise ValueError("password must contain a lowercase letter")
    if not any(ch.isupper() for ch in normalized):
        raise ValueError("password must contain an uppercase letter")
    if not any(ch.isdigit() for ch in normalized):
        raise ValueError("password must contain a digit")
    if not any(not ch.isalnum() for ch in normalized):
        raise ValueError("password must contain a special character")
    return normalized


def normalize_plot_number(value: str) -> str:
    normalized = normalize_plain_text(value, max_length=20, field_name="plot_number")
    if not _PLOT_RE.fullmatch(normalized):
        raise ValueError("plot_number contains unsupported characters")
    return normalized


def normalize_full_name(value: str) -> str:
    return normalize_plain_text(value, max_length=120, field_name="full_name")


def normalize_phone_key(value: str) -> str:
    normalized = normalize_plain_text(value, max_length=32, field_name="phone")
    digits = "".join(ch for ch in normalized if ch.isdigit())
    if len(digits) < 7 or len(digits) > 15:
        raise ValueError("phone must contain 7 to 15 digits")
    return normalized


def normalize_account_phone(value: str) -> str:
    normalized = normalize_phone_key(value)
    digits = "".join(ch for ch in normalized if ch.isdigit())
    if digits.startswith("00") and len(digits) > 2:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("9"):
        return f"+7{digits}"
    if len(digits) == 11 and digits[0] in {"7", "8"}:
        return f"+7{digits[-10:]}"
    return f"+{digits}"


def normalize_vehicle_number(value: str) -> str:
    normalized = normalize_plain_text(value, max_length=20, field_name="vehicle_number").upper()
    if not _VEHICLE_RE.fullmatch(normalized):
        raise ValueError("vehicle_number contains unsupported characters")
    return normalized
