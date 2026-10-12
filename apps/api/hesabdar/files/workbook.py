from __future__ import annotations

import csv
from io import BytesIO, StringIO

import xlwt
from openpyxl import Workbook
from openpyxl.cell.cell import Cell

from hesabdar.errors import AppError
from hesabdar.messages import FILE_UNSUPPORTED


def write_workbook(sheets: list[dict], file_format: str) -> bytes:
    if file_format == "xlsx":
        return _write_xlsx(sheets)
    if file_format == "xls":
        return _write_xls(sheets)
    if file_format == "csv":
        return _write_csv(sheets)
    raise AppError("file.unsupported_type", FILE_UNSUPPORTED, 400)


def _write_xlsx(sheets: list[dict]) -> bytes:
    book = Workbook()
    first = book.active
    for index, sheet in enumerate(sheets):
        worksheet = first if index == 0 else book.create_sheet()
        worksheet.title = sheet["name"]
        worksheet.sheet_view.rightToLeft = True
        formulas = sheet.get("formulas") or set()
        for row_index, row in enumerate(sheet["rows"]):
            for column_index, value in enumerate(row):
                if value is None:
                    continue
                cell = worksheet.cell(row_index + 1, column_index + 1)
                _write_xlsx_cell(cell, value, (row_index, column_index) in formulas)
    if not sheets:
        first.title = "خالی"
        first.sheet_view.rightToLeft = True
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def _write_xlsx_cell(cell: Cell, value: str, formula: bool) -> None:
    cell.value = value
    if formula:
        return
    cell.number_format = "@"
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"


def _write_xls(sheets: list[dict]) -> bytes:
    book = xlwt.Workbook(encoding="utf-8")
    if not sheets:
        book.add_sheet("خالی")
    for sheet in sheets:
        worksheet = book.add_sheet(sheet["name"][:31] or "برگه")
        for row_index, row in enumerate(sheet["rows"]):
            for column_index, value in enumerate(row):
                if value is not None:
                    worksheet.write(row_index, column_index, value)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _write_csv(sheets: list[dict]) -> bytes:
    rows = sheets[0]["rows"] if sheets else []
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue().encode("utf-8-sig")
