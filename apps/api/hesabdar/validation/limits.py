from __future__ import annotations

from hesabdar.errors import AppError
from hesabdar.messages import SHEET_TOO_LONG


def assert_complete(read) -> None:
    if any(sheet.truncated for sheet in read.sheets):
        raise AppError("output.invalid", SHEET_TOO_LONG, 422)
