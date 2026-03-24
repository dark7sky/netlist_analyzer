from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


NUMERIC_PATTERN = re.compile(
    r"^(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(?P<suffix>[A-Za-z]+)?$"
)

SUFFIX_TO_EXPONENT = {
    "": 0,
    "t": 12,
    "g": 9,
    "meg": 6,
    "k": 3,
    "m": -3,
    "u": -6,
    "n": -9,
    "p": -12,
    "f": -15,
}
ENGINEERING_EXPONENTS = [12, 9, 6, 3, 0, -3, -6, -9, -12, -15]
EXPONENT_TO_SUFFIX = {value: key for key, value in SUFFIX_TO_EXPONENT.items()}


def parse_spice_number(text: str) -> Decimal | None:
    stripped = text.strip()
    if not stripped:
        return None

    match = NUMERIC_PATTERN.match(stripped)
    if not match:
        return None

    suffix = (match.group("suffix") or "").strip()
    normalized_suffix = "meg" if suffix.lower() == "meg" else suffix.lower()
    if normalized_suffix not in SUFFIX_TO_EXPONENT:
        return None

    try:
        base = Decimal(match.group("number"))
    except InvalidOperation:
        return None

    return base * (Decimal(10) ** SUFFIX_TO_EXPONENT[normalized_suffix])


def normalize_spice_number(text: str) -> str:
    stripped = text.strip()
    parsed = parse_spice_number(stripped)
    if parsed is None:
        return stripped
    return format_spice_number(parsed)


def format_spice_number(value: Decimal) -> str:
    if value == 0:
        return "0"

    abs_value = abs(value)
    exponent = 0
    for candidate in ENGINEERING_EXPONENTS:
        scaled = abs_value / (Decimal(10) ** candidate)
        if Decimal("1") <= scaled < Decimal("1000"):
            exponent = candidate
            break
    else:
        exponent = 0

    scaled_value = value / (Decimal(10) ** exponent)
    return f"{_format_decimal(scaled_value)}{EXPONENT_TO_SUFFIX[exponent]}"


def normalize_numeric_params(params: dict[str, str]) -> dict[str, str]:
    return {key: normalize_spice_number(value) for key, value in params.items()}


def numeric_multiplier(value: str) -> float:
    parsed = parse_spice_number(value)
    if parsed is None:
        return 1.0
    return float(parsed)


def sort_numeric_desc(value: str) -> tuple[int, Decimal]:
    parsed = parse_spice_number(value)
    if parsed is None:
        return (1, Decimal("-Infinity"))
    return (0, -parsed)


def normalize_search_value(value: str) -> str:
    return normalize_spice_number(value).lower()


def format_count(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return _format_decimal(Decimal(str(value)))


def _format_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
