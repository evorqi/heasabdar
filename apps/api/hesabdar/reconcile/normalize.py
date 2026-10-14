from __future__ import annotations

import re

from hesabdar.inspection.classify import parse_number, translate_digits

_ZWNJ = "\u200c"


def normalize_compare(value: str | None) -> str | None:
    if value is None:
        return None
    text = translate_digits(value)
    text = text.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return None
    return text.casefold()


def header_key(value: str) -> str:
    return (normalize_compare(value) or "").replace(_ZWNJ, "").replace(" ", "")


def parse_amount(value: str | None):
    if value is None:
        return None
    number, warning = parse_number(value)
    if warning or number is None:
        return None
    return number
