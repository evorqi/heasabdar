from __future__ import annotations

import re
from decimal import Decimal

from hesabdar.inspection.classify import (
    IDENTIFIER_ROLES,
    classify_date,
    looks_like_national_id,
    parse_number,
    translate_digits,
)

ZWNJ = "\u200c"
REQUIRED_ROLES = IDENTIFIER_ROLES | {"amount", "date"}
_DANGER_START = ("=", "+", "-", "@")
_BIDI = frozenset("\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def clean_cell(
    raw: str | None,
    *,
    header: bool,
    kind: str,
    role: str | None,
    formula: bool,
    error_token: str | None,
) -> tuple[str | None, list[tuple[str, str, str]], list[tuple[str, str]]]:
    """برمی‌گرداند (مقدار نهایی، تغییرات، ردشده‌ها).

    هر تغییر یک سه‌تایی (rule_id, before, after) است.
    هر ردشده یک دوتایی (rule_id, message) است و مقدار را عوض نمی‌کند.
    """
    if formula:
        return raw, [], [("formula.kept", "فرمول دست نخورده است.")]
    if error_token:
        return raw, [], [("excel.error", "خطای نمایشی فرمول دست نخورده است.")]
    if raw in (None, ""):
        if not header and role in REQUIRED_ROLES:
            return raw, [], [("column.empty_required", "خانه خالی در ستون لازم است.")]
        return raw, [], []
    if header:
        return _finish_text(raw), _text_changes(raw), []
    if kind == "identifier" or role in IDENTIFIER_ROLES:
        return _clean_identifier(raw)
    if kind == "date" or role == "date":
        return _clean_date(raw)
    if kind in {"number", "currency"} or role == "amount":
        return _clean_number(raw)
    return _finish_text(raw), _text_changes(raw), []


def neutralize_csv(value: str | None, produced_by_parse: bool) -> str | None:
    if value is None or produced_by_parse or not value:
        return value
    if value[0] in _DANGER_START or value[0] in _BIDI:
        return "'" + value
    return value


def national_id_checksum_ok(digits: str) -> bool | None:
    if not re.fullmatch(r"\d{10}", digits):
        return None
    total = sum(int(digits[index]) * (10 - index) for index in range(9))
    remainder = total % 11
    check = int(digits[9])
    if remainder < 2:
        return check == remainder
    return check == (11 - remainder)


def _clean_identifier(raw: str) -> tuple[str, list[tuple[str, str, str]], list[tuple[str, str]]]:
    current, changes = _apply_text(raw)
    translated = translate_digits(current)
    if translated != current:
        changes.append(("identifier.leading_zeros", current, translated))
        current = translated
    skipped: list[tuple[str, str]] = []
    if looks_like_national_id(current) and national_id_checksum_ok(current) is False:
        skipped.append(
            (
                "identifier.national_id_checksum",
                "رقم کنترلی کد ملی معتبر نیست. این هشدار مقدار را عوض نمی‌کند.",
            )
        )
    return current, changes, skipped


def _clean_number(raw: str) -> tuple[str, list[tuple[str, str, str]], list[tuple[str, str]]]:
    current, changes = _apply_text(raw, letters=False)
    number, warning = parse_number(current)
    if warning == "number.ambiguous":
        return current, changes, [("number.ambiguous", "عدد بیش از یک تفسیر دارد و تغییر نکرد.")]
    if number is None:
        current, letter_changes = _apply_text(current, spaces=False)
        changes.extend(letter_changes)
        return current, changes, [("number.not_numeric", "این مقدار عدد بی‌ابهام نیست و تغییر نکرد.")]
    rendered = _render_decimal(number) + _unit_suffix(raw)
    if rendered != current:
        changes.append(("number.parse", current, rendered))
    return rendered, changes, []


def _clean_date(raw: str) -> tuple[str, list[tuple[str, str, str]], list[tuple[str, str]]]:
    current, changes = _apply_text(raw)
    parsed, warning = classify_date(current)
    if warning == "date.ambiguous":
        return current, changes, [("date.ambiguous", "تاریخ مبهم است و تغییر نکرد.")]
    if warning == "date.invalid":
        return current, changes, [("date.invalid", "تاریخ نامعتبر است و اصلاح حدسی نشد.")]
    iso = _iso_date(current)
    if iso:
        parsed = iso
        rule = "date.parse_gregorian"
    elif parsed:
        rule = "date.parse_jalali" if _looks_jalali(current) else "date.parse_gregorian"
    else:
        return current, changes, []
    if parsed != current:
        changes.append((rule, current, parsed))
        current = parsed
    return current, changes, []


def _finish_text(raw: str) -> str:
    current, _changes = _apply_text(raw)
    return current


def _text_changes(raw: str) -> list[tuple[str, str, str]]:
    _current, changes = _apply_text(raw)
    return changes


def _apply_text(
    raw: str, *, spaces: bool = True, letters: bool = True
) -> tuple[str, list[tuple[str, str, str]]]:
    current = raw
    changes: list[tuple[str, str, str]] = []
    steps: list[tuple[str, object]] = []
    if spaces:
        steps.extend(
            (
                ("text.trim", _trim),
                ("text.collapse_spaces", _collapse),
            )
        )
    if letters:
        steps.extend(
            (
                ("text.arabic_yeh", _yeh),
                ("text.arabic_kaf", _kaf),
            )
        )
    for rule_id, function in steps:
        updated = function(current)
        if updated != current:
            changes.append((rule_id, current, updated))
            current = updated
    return current, changes


def _trim(value: str) -> str:
    return value.strip(" \t\u00a0")


def _collapse(value: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", value)


def _yeh(value: str) -> str:
    return value.replace("ي", "ی").replace("ى", "ی")


def _kaf(value: str) -> str:
    return value.replace("ك", "ک")


def _unit_suffix(raw: str) -> str:
    if "تومان" in raw:
        return " تومان"
    if "ریال" in raw:
        return " ریال"
    return ""


def _render_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _iso_date(value: str) -> str | None:
    matched = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:T\d{2}:\d{2}:\d{2})?", value)
    if not matched:
        return None
    return matched.group(1)


def _looks_jalali(value: str) -> bool:
    translated = translate_digits(value)
    matched = re.search(r"(\d{4})", translated)
    if not matched:
        return False
    year = int(matched.group(1))
    return 1300 <= year <= 1499
