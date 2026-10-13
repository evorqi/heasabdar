from __future__ import annotations

from hesabdar.errors import AppError
from hesabdar.inspection.readers import read_workbook


def measure(data: bytes, file_format: str, filename: str) -> dict | None:
    try:
        read = read_workbook(data, file_format, filename or "نسخه")
    except AppError:
        return None
    rows = 0
    columns = 0
    for sheet in read.sheets:
        rows += max(len(sheet.rows) - 1, 0)
        width = max((len(row) for row in sheet.rows), default=0)
        columns = max(columns, width)
    return {"rows": rows, "columns": columns, "sheets": len(read.sheets)}


def change_report(
    before: dict | None,
    after: dict | None,
    sha256_before: str | None,
    sha256_after: str | None,
) -> dict | None:
    if after is None and before is None:
        return None
    return {
        "rows_before": None if before is None else before["rows"],
        "columns_before": None if before is None else before["columns"],
        "sheets_before": None if before is None else before["sheets"],
        "rows_after": None if after is None else after["rows"],
        "columns_after": None if after is None else after["columns"],
        "sheets_after": None if after is None else after["sheets"],
        "sha256_before": sha256_before,
        "sha256_after": sha256_after,
    }
