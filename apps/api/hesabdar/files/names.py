from __future__ import annotations

from urllib.parse import quote
from pathlib import PurePath

from hesabdar.errors import AppError
from hesabdar.messages import FILE_INVALID_NAME, FILE_UNSUPPORTED

MAX_NAME_LENGTH = 180
ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}


def validate_display_name(filename: str) -> str:
    """نام فقط برای نمایش است و هرگز بخشی از مسیر ذخیره نمی‌شود."""
    cleaned = (filename or "").strip()
    if not cleaned or len(cleaned) > MAX_NAME_LENGTH:
        raise AppError("file.invalid_name", FILE_INVALID_NAME, 400)
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise AppError("file.invalid_name", FILE_INVALID_NAME, 400)
    if "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."} or ".." in cleaned.split("."):
        raise AppError("file.invalid_name", FILE_INVALID_NAME, 400)
    stem, dot, extension = cleaned.rpartition(".")
    if not dot or not stem or set(stem) <= {"."}:
        raise AppError("file.invalid_name", FILE_INVALID_NAME, 400)
    if extension.lower() not in ALLOWED_EXTENSIONS:
        raise AppError("file.unsupported_type", FILE_UNSUPPORTED, 400)
    return cleaned


def content_disposition(original_name: str) -> str:
    suffix = PurePath(original_name).suffix.lower()
    if suffix not in {".xlsx", ".xls", ".csv"}:
        suffix = ""
    encoded = quote(original_name, safe="")
    return f"attachment; filename=\"download{suffix}\"; filename*=UTF-8''{encoded}"


def safe_echo_name(filename: str) -> str:
    kept = []
    for char in filename or "":
        if ord(char) < 32 or ord(char) == 127 or char in {"/", "\\"}:
            continue
        kept.append(char)
    echo = "".join(kept).strip()
    if len(echo) > MAX_NAME_LENGTH:
        echo = echo[:MAX_NAME_LENGTH]
    return echo or "فایل"
