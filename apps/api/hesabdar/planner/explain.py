from __future__ import annotations

import re

from hesabdar.inspection.classify import translate_digits

_NUMBER = re.compile(r"[0-9۰-۹٠-٩]+(?:[./٫][0-9۰-۹٠-٩]+)?")


def number_tokens(text: str) -> set[str]:
    found = set()
    for match in _NUMBER.findall(text):
        token = translate_digits(match).replace("٫", ".").replace("/", ".")
        if token.endswith("."):
            token = token[:-1]
        found.add(token)
    return found


def consistent(text: str, metrics: dict[str, str]) -> bool:
    allowed: set[str] = set()
    for value in metrics.values():
        allowed |= number_tokens(str(value))
    return number_tokens(text) <= allowed


def render(template: str, metrics: dict[str, str]) -> str:
    text = template.format(**metrics)
    if not consistent(text, metrics):
        raise ValueError("summary number is outside the engine metrics")
    return text
