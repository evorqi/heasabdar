from __future__ import annotations

from decimal import Decimal

from hesabdar.errors import AppError
from hesabdar.files.service import FileService
from hesabdar.inspection.build import build_report
from hesabdar.inspection.readers import read_workbook
from hesabdar.messages import OPERATION_INVALID, REQUEST_INVALID
from hesabdar.reconcile.engine import load_table
from hesabdar.reconcile.normalize import header_key, parse_amount
from hesabdar.validation.limits import assert_complete


def load_sheet(files: FileService, workspace_id: str, file_id: str) -> tuple[dict, dict]:
    meta = files.get_file(workspace_id, file_id)
    _record, data = files.read_version(workspace_id, meta["current_version_id"])
    read = read_workbook(data, meta["format"], meta["original_name"])
    assert_complete(read)
    built = build_report(read, file_id, meta["current_version_id"], meta["format"])
    if not built["sheets"]:
        raise AppError("request.invalid", REQUEST_INVALID, 400)
    summary = max(built["sheets"], key=lambda sheet: sheet["data_row_count"])
    raw = next(sheet for sheet in read.sheets if sheet.name == summary["name"])
    return meta, load_table(raw, summary)


def amount_columns(table: dict) -> list[str]:
    found = []
    for name, role in table["roles"].items():
        key = header_key(name)
        if role == "amount" or "مبلغ" in key or "فروش" in key:
            found.append(name)
    return found


def grid(table: dict, rows: list[dict], extra: tuple[str, list] | None = None) -> list[dict]:
    headers = list(table["headers"])
    extra_values = None
    if extra is not None:
        headers.append(extra[0])
        extra_values = extra[1]
    body = [headers]
    for index, row in enumerate(rows):
        values = [row.get(name) for name in table["headers"]]
        if extra_values is not None:
            values.append(extra_values[index])
        body.append(values)
    return [{"name": table["sheet"] or "برگه", "rows": body}]


def assert_output(data: bytes, data_rows: int, header_name: str | None = None) -> None:
    try:
        read = read_workbook(data, "xlsx", "نتیجه.xlsx")
    except AppError:
        raise AppError("output.invalid", OPERATION_INVALID, 422) from None
    if len(read.sheets) != 1 or not read.sheets[0].rows:
        raise AppError("output.invalid", OPERATION_INVALID, 422)
    if max(len(read.sheets[0].rows) - 1, 0) != data_rows:
        raise AppError("output.invalid", OPERATION_INVALID, 422)
    if header_name is not None:
        headers = [cell.raw for cell in read.sheets[0].rows[0]]
        if header_name not in headers:
            raise AppError("output.invalid", OPERATION_INVALID, 422)


def compare(amount: Decimal, op: str, threshold: Decimal) -> bool:
    if op == "gt":
        return amount > threshold
    if op == "lt":
        return amount < threshold
    if op == "gte":
        return amount >= threshold
    if op == "lte":
        return amount <= threshold
    raise AppError("request.invalid", REQUEST_INVALID, 400)


def money(value) -> Decimal | None:
    return parse_amount(value)
