from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

import jdatetime

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
ERROR_TOKENS = ("#REF!", "#VALUE!", "#N/A", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!")
IDENTIFIER_ROLES = {
    "national_id",
    "phone",
    "invoice_no",
    "product_code",
    "employee_id",
    "customer_id",
    "account_no",
}
MONTHS = {
    "فروردین": 1,
    "اردیبهشت": 2,
    "خرداد": 3,
    "تیر": 4,
    "مرداد": 5,
    "شهریور": 6,
    "مهر": 7,
    "آبان": 8,
    "آذر": 9,
    "دی": 10,
    "بهمن": 11,
    "اسفند": 12,
}
ROLE_KEYS = (
    ("کدملی", "national_id"),
    ("شمارهملی", "national_id"),
    ("nationalid", "national_id"),
    ("کدپرسنلی", "employee_id"),
    ("شناسهکارمند", "employee_id"),
    ("employeeid", "employee_id"),
    ("شمارهفاکتور", "invoice_no"),
    ("invoice", "invoice_no"),
    ("کدکالا", "product_code"),
    ("کدمحصول", "product_code"),
    ("sku", "product_code"),
    ("شمارهحساب", "account_no"),
    ("شناسهمشتری", "customer_id"),
    ("تلفن", "phone"),
    ("موبایل", "phone"),
    ("همراه", "phone"),
    ("phone", "phone"),
    ("مبلغ", "amount"),
    ("قیمت", "amount"),
    ("فروش", "amount"),
    ("بدهکار", "amount"),
    ("بستانکار", "amount"),
    ("amount", "amount"),
    ("price", "amount"),
    ("تاریخ", "date"),
    ("date", "date"),
    ("ناممشتری", "person_name"),
    ("نام", "person_name"),
    ("name", "person_name"),
    ("شهر", "city"),
    ("استان", "city"),
    ("city", "city"),
)


@dataclass
class CellView:
    raw: str | None
    parsed: str | None = None
    warnings: list[str] = field(default_factory=list)
    formula: bool = False
    error_token: str | None = None
    excel_number: Decimal | None = None


@dataclass
class ColumnView:
    name: str
    normalized_name: str
    index: int
    kind: str
    kind_confidence: float
    role_hints: list[str]
    empty_count: int
    samples: list[str]
    role_from_header: bool


def compact_header(value: str) -> str:
    text = normalize_letters(value).replace("\u200c", "").replace(" ", "").casefold()
    return text


def normalize_letters(value: str) -> str:
    return (
        value.replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
        .replace("\u00a0", " ")
    )


def normalize_header(value: str) -> str:
    text = normalize_letters(value).strip()
    text = re.sub(r"[ \t]+", " ", text)
    return text.casefold()


def role_from_header(name: str) -> str | None:
    compact = compact_header(name)
    if not compact:
        return None
    best: tuple[int, str] | None = None
    for key, role in ROLE_KEYS:
        if key in compact and (best is None or len(key) > best[0]):
            best = (len(key), role)
    return None if best is None else best[1]


def parse_number(raw: str) -> tuple[Decimal | None, str | None]:
    text = translate_digits(raw)
    text = text.replace("ریال", "").replace("تومان", "")
    text = text.replace("\u200c", "").replace(" ", "").replace("٬", "").replace("،", ",")
    text = text.strip()
    if not text or text in {"-", "+", ".", ","}:
        return None, None
    if re.fullmatch(r"[+-]?\d+", text):
        return Decimal(text), None
    if re.fullmatch(r"[+-]?\d{1,3}[.,]\d{3}", text):
        return None, "number.ambiguous"
    if re.fullmatch(r"[+-]?\d{1,3}(,\d{3}){2,}", text):
        return Decimal(text.replace(",", "")), None
    if re.fullmatch(r"[+-]?\d{1,3}(\.\d{3}){2,}", text):
        return Decimal(text.replace(".", "")), None
    if re.fullmatch(r"[+-]?\d+\.\d+", text):
        return _decimal(text), None
    if re.fullmatch(r"[+-]?\d+,\d{1,2}", text):
        return _decimal(text.replace(",", ".")), None
    return None, None


def classify_date(raw: str) -> tuple[str | None, str | None]:
    """برمی‌گرداند (مقدار تجزیه‌شده، هشدار). اگر تاریخ نباشد هر دو تهی است."""
    text = translate_digits(raw).strip()
    named = re.fullmatch(r"(\d{1,2})\s+([^\d\s]+)\s+(\d{4})", text)
    if named:
        day, month_name, year = int(named.group(1)), named.group(2), int(named.group(3))
        month = MONTHS.get(normalize_letters(month_name))
        if month and 1300 <= year <= 1499:
            return _jalali(year, month, day)
        return None, None
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{1,2}", text):
        return None, "date.ambiguous"
    matched = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if not matched:
        return None, None
    year, month, day = (int(part) for part in matched.groups())
    if 1300 <= year <= 1499:
        return _jalali(year, month, day)
    if 1900 <= year <= 2100:
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None, "date.invalid"
        return parsed.isoformat(), None
    return None, "date.ambiguous"


def translate_digits(value: str) -> str:
    return value.translate(PERSIAN_DIGITS)


def looks_like_national_id(raw: str) -> bool:
    digits = translate_digits(raw).strip()
    return bool(re.fullmatch(r"\d{10}", digits))


def looks_like_phone(raw: str) -> bool:
    digits = translate_digits(raw).strip().replace(" ", "").replace("-", "")
    return bool(re.fullmatch(r"0\d{10}", digits) or re.fullmatch(r"\+98\d{10}", digits))


def _jalali(year: int, month: int, day: int) -> tuple[str | None, str | None]:
    try:
        jdatetime.date(year, month, day)
    except ValueError:
        return None, "date.invalid"
    return f"{year:04d}-{month:02d}-{day:02d}", None


def _decimal(text: str) -> tuple[Decimal | None, str | None]:
    try:
        return Decimal(text), None
    except InvalidOperation:
        return None, None
